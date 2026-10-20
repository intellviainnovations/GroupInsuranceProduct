"""Payload protection for USGIC (docs/contracts/usgic-gpa.md, "Payload protection").

Implements AES-256-CBC encryption per ABHI API security specification:
  - Algorithm: AES-256 (32-byte key)
  - Mode:      CBC (Cipher Block Chaining)
  - Padding:   PKCS7 (identical to PKCS5 for AES)
  - IV:        16-byte, randomly generated per encryption
  - Wire format: ``<Base64(IV)>.<Base64(EncryptedPayload)>``

The IV is never reused with the same key. It is transmitted alongside the ciphertext, separated
by a dot, as specified by the ABHI security contract.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Protocol

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

_logger = logging.getLogger("backend.adapters.insurer.usgic.cipher")

AES_BLOCK_BITS = 128  # AES block size is always 128 bits (16 bytes)
AES_256_KEY_BYTES = 32


class CipherNotConfigured(Exception):
    """The payload cipher is not configured; nothing may be sent (fails closed)."""


class CipherError(Exception):
    """A reply could not be decrypted."""


class PayloadCipher(Protocol):
    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...

    @property
    def configured(self) -> bool: ...


class UnconfiguredCipher:
    configured = False

    def encrypt(self, plaintext: str) -> str:
        raise CipherNotConfigured

    def decrypt(self, ciphertext: str) -> str:
        raise CipherNotConfigured


class Aes256CbcCipher:
    """AES-256-CBC with PKCS7 padding and per-request random IV.

    Encryption output: ``<Base64(IV)>.<Base64(EncryptedPayload)>``
    Decryption input:  same format — split on ``'.'``, decode both halves from Base64.

    Security invariants enforced:
    - Key must be exactly 32 bytes (256 bits).
    - IV is 16 bytes, generated from ``os.urandom`` (CSPRNG) on every encrypt call.
    - IV is never reused with the same key (guaranteed by random generation).
    """

    configured = True

    def __init__(self, key: bytes) -> None:
        if len(key) != AES_256_KEY_BYTES:
            raise ValueError(
                f"AES-256 key must be exactly {AES_256_KEY_BYTES} bytes, got {len(key)}"
            )
        self._key = key

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext to ``<Base64(IV)>.<Base64(Ciphertext)>``.

        Steps (per ABHI spec):
        1. Convert plaintext to UTF-8 bytes.
        2. Generate a random 16-byte IV.
        3. Pad plaintext with PKCS7.
        4. Encrypt with AES-256-CBC.
        5. Base64-encode the ciphertext and IV separately.
        6. Return ``<Base64(IV)>.<Base64(Ciphertext)>``.
        """
        # STEP 1: Convert plaintext to bytes
        plaintext_bytes = plaintext.encode("utf-8")

        # STEP 2: Generate a random IV (16 bytes, CSPRNG)
        iv = os.urandom(16)

        # STEP 3: Pad with PKCS7
        padder = PKCS7(AES_BLOCK_BITS).padder()
        padded = padder.update(plaintext_bytes) + padder.finalize()

        # STEP 4: Encrypt with AES-256-CBC
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        encrypted_bytes = encryptor.update(padded) + encryptor.finalize()

        # STEP 5 & 6: Base64-encode and compose
        iv_b64 = base64.b64encode(iv).decode("ascii")
        encrypted_b64 = base64.b64encode(encrypted_bytes).decode("ascii")
        return f"{iv_b64}.{encrypted_b64}"

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt ``<Base64(IV)>.<Base64(Ciphertext)>`` back to plaintext.

        Steps (per ABHI spec):
        1. Split the payload on ``'.'``.
        2. Base64-decode both IV and encrypted data.
        3. Decrypt with AES-256-CBC using the same key.
        4. Remove PKCS7 padding.
        5. Return the UTF-8 plaintext.
        """
        try:
            # STEP 1: Split the payload
            parts = ciphertext.split(".")
            if len(parts) != 2:
                raise CipherError("payload must be <Base64(IV)>.<Base64(EncryptedData)>")

            iv_b64, encrypted_b64 = parts

            # STEP 2: Decode Base64
            iv = base64.b64decode(iv_b64)
            encrypted_bytes = base64.b64decode(encrypted_b64)

            if len(iv) != 16:
                raise CipherError(f"IV must be 16 bytes, got {len(iv)}")

            # STEP 3: Decrypt
            cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv))
            decryptor = cipher.decryptor()
            padded = decryptor.update(encrypted_bytes) + decryptor.finalize()

            # STEP 4: Remove PKCS7 padding
            unpadder = PKCS7(AES_BLOCK_BITS).unpadder()
            plaintext_bytes = unpadder.update(padded) + unpadder.finalize()

            # STEP 5: Return UTF-8 string
            return plaintext_bytes.decode("utf-8")

        except CipherError:
            raise
        except Exception as exc:
            raise CipherError(f"decryption failed: {type(exc).__name__}") from exc


def build_cipher(name: str, *, key: bytes | None = None) -> PayloadCipher:
    """Return the configured cipher.

    ``name`` values:
    - ``"unconfigured"``: fail-closed placeholder (no key needed).
    - ``"aes-256-cbc"``: production AES-256-CBC cipher (key required, must be 32 bytes).
    """
    if name == "unconfigured":
        return UnconfiguredCipher()
    if name == "aes-256-cbc":
        if key is None:
            raise CipherNotConfigured("aes-256-cbc cipher requires a key")
        return Aes256CbcCipher(key)
    raise CipherNotConfigured(f"unknown cipher: {name}")
