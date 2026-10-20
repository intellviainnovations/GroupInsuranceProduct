"""Tests for the AES-256-CBC cipher and ABHI APIM subscription key integration.

Covers:
- Encrypt → decrypt round-trip with known and random keys
- Wire format: <Base64(IV)>.<Base64(Ciphertext)>
- IV uniqueness across encryptions (never reused)
- Key length validation (must be exactly 32 bytes)
- Decryption of payloads with tampered IV, ciphertext, or format
- UnconfiguredCipher fail-closed behaviour
- build_cipher factory function
- ABHI APIM subscription key in request headers
"""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from backend.adapters.insurer.usgic.adapter import UsgicConfig, UsgicInsurer
from backend.adapters.insurer.usgic.cipher import (
    AES_256_KEY_BYTES,
    Aes256CbcCipher,
    CipherError,
    CipherNotConfigured,
    UnconfiguredCipher,
    build_cipher,
)


# ---------------------------------------------------------------- fixtures

KNOWN_KEY = b"01234567890123456789012345678901"  # exactly 32 bytes
assert len(KNOWN_KEY) == 32


def jwt(exp: datetime) -> str:
    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'HS256'})}.{part({'exp': int(exp.timestamp())})}.c2ln"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


CODES = {("GENDER", "F"): "Female", ("STATE", "TN"): "TAMIL NADU"}


# ---------------------------------------------------------------- Aes256CbcCipher


class TestAes256CbcCipher:
    def test_roundtrip_simple_text(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        plaintext = "Hello, ABHI API!"
        encrypted = cipher.encrypt(plaintext)
        assert cipher.decrypt(encrypted) == plaintext

    def test_roundtrip_json_payload(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        payload = json.dumps({"AccountNo": "509900011001", "Amount": "1000.00"})
        encrypted = cipher.encrypt(payload)
        decrypted = cipher.decrypt(encrypted)
        assert json.loads(decrypted) == json.loads(payload)

    def test_roundtrip_empty_string(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        encrypted = cipher.encrypt("")
        assert cipher.decrypt(encrypted) == ""

    def test_roundtrip_unicode(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        text = "मुंबई शाखा — ₹10,000"
        assert cipher.decrypt(cipher.encrypt(text)) == text

    def test_roundtrip_large_payload(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        text = "x" * 10_000
        assert cipher.decrypt(cipher.encrypt(text)) == text

    def test_wire_format_is_base64_dot_base64(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        encrypted = cipher.encrypt("test data")
        parts = encrypted.split(".")
        assert len(parts) == 2, "format must be <IV>.<Ciphertext>"
        iv_bytes = base64.b64decode(parts[0])
        assert len(iv_bytes) == 16, "IV must be 16 bytes"
        # ciphertext must be valid base64
        base64.b64decode(parts[1])

    def test_iv_is_unique_per_encryption(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        ivs = set()
        for _ in range(100):
            encrypted = cipher.encrypt("same plaintext")
            iv_b64 = encrypted.split(".")[0]
            ivs.add(iv_b64)
        # With random 16-byte IVs, all 100 should be unique
        assert len(ivs) == 100

    def test_different_ciphertexts_for_same_plaintext(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        a = cipher.encrypt("same")
        b = cipher.encrypt("same")
        assert a != b, "same plaintext must produce different ciphertexts (different IVs)"

    def test_cross_instance_decrypt(self) -> None:
        """Encrypted by one instance, decrypted by another with the same key."""
        c1 = Aes256CbcCipher(KNOWN_KEY)
        c2 = Aes256CbcCipher(KNOWN_KEY)
        encrypted = c1.encrypt("cross-instance test")
        assert c2.decrypt(encrypted) == "cross-instance test"

    def test_wrong_key_raises_cipher_error(self) -> None:
        c1 = Aes256CbcCipher(KNOWN_KEY)
        c2 = Aes256CbcCipher(b"XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
        encrypted = c1.encrypt("secret")
        with pytest.raises(CipherError):
            c2.decrypt(encrypted)

    def test_configured_is_true(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        assert cipher.configured is True


# ---------------------------------------------------------------- key validation


class TestKeyValidation:
    def test_key_too_short(self) -> None:
        with pytest.raises(ValueError, match="32 bytes"):
            Aes256CbcCipher(b"too-short")

    def test_key_too_long(self) -> None:
        with pytest.raises(ValueError, match="32 bytes"):
            Aes256CbcCipher(b"x" * 33)

    def test_key_exactly_32_bytes(self) -> None:
        cipher = Aes256CbcCipher(b"a" * 32)
        assert cipher.configured


# ---------------------------------------------------------------- decryption failures


class TestDecryptionFailures:
    def test_missing_dot_separator(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        with pytest.raises(CipherError, match="payload must be"):
            cipher.decrypt("nodot")

    def test_extra_dots(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        with pytest.raises(CipherError, match="payload must be"):
            cipher.decrypt("a.b.c")

    def test_invalid_base64_iv(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        with pytest.raises(CipherError):
            cipher.decrypt("!!!invalid!!!.dGVzdA==")

    def test_tampered_ciphertext(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        encrypted = cipher.encrypt("original")
        iv_b64, ct_b64 = encrypted.split(".")
        # Corrupt the ciphertext
        ct_bytes = bytearray(base64.b64decode(ct_b64))
        ct_bytes[0] ^= 0xFF
        tampered = iv_b64 + "." + base64.b64encode(bytes(ct_bytes)).decode()
        with pytest.raises(CipherError):
            cipher.decrypt(tampered)

    def test_tampered_iv(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        encrypted = cipher.encrypt("original")
        iv_b64, ct_b64 = encrypted.split(".")
        # Corrupt the IV
        iv_bytes = bytearray(base64.b64decode(iv_b64))
        iv_bytes[0] ^= 0xFF
        tampered = base64.b64encode(bytes(iv_bytes)).decode() + "." + ct_b64
        # Decryption with wrong IV produces garbage or padding error
        with pytest.raises(CipherError):
            cipher.decrypt(tampered)

    def test_truncated_ciphertext(self) -> None:
        cipher = Aes256CbcCipher(KNOWN_KEY)
        encrypted = cipher.encrypt("test")
        iv_b64, ct_b64 = encrypted.split(".")
        truncated = iv_b64 + "." + ct_b64[:4]
        with pytest.raises(CipherError):
            cipher.decrypt(truncated)


# ---------------------------------------------------------------- UnconfiguredCipher


class TestUnconfiguredCipher:
    def test_encrypt_raises(self) -> None:
        cipher = UnconfiguredCipher()
        with pytest.raises(CipherNotConfigured):
            cipher.encrypt("anything")

    def test_decrypt_raises(self) -> None:
        cipher = UnconfiguredCipher()
        with pytest.raises(CipherNotConfigured):
            cipher.decrypt("anything")

    def test_configured_is_false(self) -> None:
        assert UnconfiguredCipher().configured is False


# ---------------------------------------------------------------- build_cipher factory


class TestBuildCipher:
    def test_unconfigured(self) -> None:
        cipher = build_cipher("unconfigured")
        assert not cipher.configured

    def test_aes_256_cbc(self) -> None:
        cipher = build_cipher("aes-256-cbc", key=KNOWN_KEY)
        assert cipher.configured
        assert cipher.decrypt(cipher.encrypt("hello")) == "hello"

    def test_aes_256_cbc_requires_key(self) -> None:
        with pytest.raises(CipherNotConfigured, match="requires a key"):
            build_cipher("aes-256-cbc")

    def test_unknown_cipher_name(self) -> None:
        with pytest.raises(CipherNotConfigured, match="unknown cipher"):
            build_cipher("des-ecb")


# ---------------------------------------------------------------- ABHI APIM subscription key


class TestAbhiApimSubscriptionKey:
    """Verify the Ocp-Apim-Subscription-Key header is sent when configured."""

    def _build_adapter(
        self, apim_key: str | None = None
    ) -> tuple[UsgicInsurer, list[tuple[str, httpx.Headers]]]:
        clock = Clock()
        captured: list[tuple[str, httpx.Headers]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            method = request.url.path.rsplit("/", 1)[-1]
            captured.append((method, request.headers))
            outer = json.loads(request.content)
            inner_json = base64.b64decode(outer["Data"]).decode()
            inner = json.loads(json.loads(inner_json)["Value"])
            if method == "GenerateToken":
                reply: Any = {
                    "Status": "SUCCESS",
                    "TokenId": "tid-1",  # secret-scan:allow - synthetic token id
                    "JwtToken": jwt(clock.now + timedelta(hours=1)),
                }
            else:
                reply = {
                    "Status": "SUCCESS",
                    "ReferenceNo": "SYNP900001",
                    "NetPremium": "100.00",
                    "GSTAmount": "18.00",
                    "GrossPremium": "118.00",
                }
            text = base64.b64encode(json.dumps(reply).encode()).decode()
            return httpx.Response(200, json={"response": text})

        # Use identity cipher for this test (base64 round-trip)
        class B64Cipher:
            configured = True

            def encrypt(self, plaintext: str) -> str:
                return base64.b64encode(plaintext.encode()).decode()

            def decrypt(self, ciphertext: str) -> str:
                return base64.b64decode(ciphertext).decode()

        adapter = UsgicInsurer(
            UsgicConfig(
                base_url="https://abhi-uat.invalid/api",
                user_name="TESTUSER",
                product_code="TESTPROD",
                apim_subscription_key=apim_key,
            ),
            B64Cipher(),
            lambda category, code: CODES.get((category, code)),
            transport=httpx.MockTransport(handler),
            clock=clock,
        )
        return adapter, captured

    def test_apim_key_sent_in_headers(self) -> None:
        from backend.adapters.insurer.base import ProposalRequest, Success
        from decimal import Decimal
        from datetime import date

        adapter, captured = self._build_adapter(apim_key="my-secret-subscription-key")

        req = ProposalRequest(
            our_reference_no="TEST-001",
            branch_code="0101",
            bank_customer_id="C001",
            plan_code="A",
            account_no="1234567890",
            first_name="Test",
            last_name="User",
            gender_code="F",
            date_of_birth=date(1990, 1, 1),
            mobile="9000000001",
            address1="123 Test St",
            city="TestCity",
            state_code="TN",
            pincode="600001",
            occupation_code="SALARIED",
            any_disability=False,
        )
        outcome = adapter.create_proposal(req, correlation_id=None)
        assert isinstance(outcome, Success)

        # The business call should include the APIM key (not the token call)
        business_calls = [(m, h) for m, h in captured if m != "GenerateToken"]
        assert len(business_calls) >= 1
        _, headers = business_calls[0]
        assert headers["ocp-apim-subscription-key"] == "my-secret-subscription-key"

    def test_no_apim_key_when_not_configured(self) -> None:
        from backend.adapters.insurer.base import ProposalRequest, Success
        from decimal import Decimal
        from datetime import date

        adapter, captured = self._build_adapter(apim_key=None)

        req = ProposalRequest(
            our_reference_no="TEST-002",
            branch_code="0101",
            bank_customer_id="C002",
            plan_code="A",
            account_no="1234567890",
            first_name="Test",
            last_name="User",
            gender_code="F",
            date_of_birth=date(1990, 1, 1),
            mobile="9000000001",
            address1="123 Test St",
            city="TestCity",
            state_code="TN",
            pincode="600001",
            occupation_code="SALARIED",
            any_disability=False,
        )
        outcome = adapter.create_proposal(req, correlation_id=None)
        assert isinstance(outcome, Success)

        business_calls = [(m, h) for m, h in captured if m != "GenerateToken"]
        _, headers = business_calls[0]
        assert "ocp-apim-subscription-key" not in headers


# ---------------------------------------------------------------- integration: AES cipher + adapter


class TestAesCipherWithAdapter:
    """End-to-end test: adapter uses AES-256-CBC cipher for real encrypt/decrypt."""

    def test_roundtrip_through_adapter(self) -> None:
        clock = Clock()
        cipher = Aes256CbcCipher(KNOWN_KEY)

        def handler(request: httpx.Request) -> httpx.Response:
            method = request.url.path.rsplit("/", 1)[-1]
            outer = json.loads(request.content)
            # The adapter encrypts the body with our AES cipher
            ciphertext = outer["Data"]
            # Decrypt it to verify the adapter used the cipher correctly
            plaintext = cipher.decrypt(ciphertext)
            inner = json.loads(plaintext)
            assert "Value" in inner  # adapter wraps as {"Value": "<json>"}

            if method == "GenerateToken":
                reply: Any = {
                    "Status": "SUCCESS",
                    "TokenId": "tid-aes",  # secret-scan:allow - synthetic token id
                    "JwtToken": jwt(clock.now + timedelta(hours=1)),
                }
            else:
                reply = {
                    "Status": "SUCCESS",
                    "ReferenceNo": "AES-PROP-001",
                    "NetPremium": "500.00",
                    "GSTAmount": "90.00",
                    "GrossPremium": "590.00",
                }
            # Encrypt the reply the same way the ABHI API would
            reply_json = json.dumps(reply)
            encrypted_reply = cipher.encrypt(reply_json)
            return httpx.Response(200, json={"response": encrypted_reply})

        adapter = UsgicInsurer(
            UsgicConfig(
                base_url="https://abhi-prod.invalid/api",
                user_name="PROD",
                product_code="GPA",
            ),
            cipher,
            lambda c, v: v,  # identity mapper
            transport=httpx.MockTransport(handler),
            clock=clock,
        )

        from backend.adapters.insurer.base import ProposalRequest, Success
        from datetime import date
        from decimal import Decimal

        req = ProposalRequest(
            our_reference_no="AES-REF-001",
            branch_code="0101",
            bank_customer_id="C001",
            plan_code="A",
            account_no="1234567890",
            first_name="Test",
            last_name="User",
            gender_code="F",
            date_of_birth=date(1990, 1, 1),
            mobile="9000000001",
            address1="123 Test St",
            city="TestCity",
            state_code="TN",
            pincode="600001",
            occupation_code="SALARIED",
            any_disability=False,
        )
        outcome = adapter.create_proposal(req, correlation_id=None)
        assert isinstance(outcome, Success)
        assert outcome.data.proposal_no == "AES-PROP-001"
        assert outcome.data.gross_premium == Decimal("590.00")
