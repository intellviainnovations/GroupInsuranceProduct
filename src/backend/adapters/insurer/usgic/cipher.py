"""Payload protection for USGIC (docs/contracts/usgic-gpa.md, "Payload protection").

The algorithm, mode, key and IV handling are not in the document we hold (Q26). Until they are
known and verified against the insurer's sample ciphertexts in UAT, the only cipher is
``UnconfiguredCipher``, which raises before anything can be sent. There is no plaintext fallback.
"""

from __future__ import annotations

from typing import Protocol


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


def build_cipher(name: str) -> PayloadCipher:
    """Return the configured cipher. Only ``unconfigured`` exists until Q26 is answered."""
    if name == "unconfigured":
        return UnconfiguredCipher()
    raise CipherNotConfigured
