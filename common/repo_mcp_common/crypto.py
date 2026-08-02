"""Encryption for credentials stored in the database."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from .env import secrets_key


class DecryptionError(RuntimeError):
    """A stored credential could not be decrypted with the configured key."""


class SecretBox:
    """Fernet, keyed from the environment.

    Fernet rather than raw AES: it is authenticated, versioned, and hard to
    hold wrongly. The cost is that ciphertext is not deterministic, so secrets
    cannot be looked up by value — which is fine, they are looked up by name.
    """

    def __init__(self, key: str | None = None) -> None:
        self._fernet = Fernet((key or secrets_key()).encode())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            # Almost always a changed or mismatched SECRETS_KEY rather than
            # corruption, and saying so saves an hour of looking at the wrong
            # thing.
            raise DecryptionError(
                "cannot decrypt a stored credential: SECRETS_KEY does not match "
                "the key it was encrypted with. Restore the original key, or "
                "re-enter the affected credentials."
            ) from exc


def generate_key() -> str:
    """A fresh Fernet key, for `repo-mcp-admin generate-key`."""
    return Fernet.generate_key().decode()
