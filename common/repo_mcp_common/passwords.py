"""Password hashing and policy for local administrator accounts."""

from __future__ import annotations

import secrets
import string

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

#: Argon2id with the argon2-cffi defaults, which track the RFC 9106 guidance.
_hasher = PasswordHasher()

MIN_LENGTH = 12


class WeakPassword(ValueError):
    """The password does not meet the minimum policy."""


def hash_password(password: str) -> str:
    validate(password)
    return _hasher.hash(password)


def verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        # A mismatch and an unparseable stored hash are both "no". Anything
        # else here would leak whether the account exists.
        return False


#: A real hash of a value nobody can supply, verified against when the account
#: does not exist so a missing user and a wrong password take the same time.
DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash uses weaker parameters than the current ones."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def validate(password: str) -> None:
    """Enforce a floor, not a maze.

    Length does more for resistance than a character-class matrix, and complex
    rules push people towards predictable substitutions. The one composition
    check here exists to catch a password that is a single repeated character.
    """
    if len(password) < MIN_LENGTH:
        raise WeakPassword(f"password must be at least {MIN_LENGTH} characters")
    if len(set(password)) < 5:
        raise WeakPassword("password must use at least 5 distinct characters")


def generate(length: int = 24) -> str:
    """A random password for the bootstrap flow when none is supplied."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(length))
