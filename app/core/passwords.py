"""Password policy and Argon2id helpers for local authentication."""

import unicodedata
from functools import lru_cache

from pwdlib import PasswordHash

MIN_PASSWORD_LENGTH = 15
MAX_PASSWORD_LENGTH = 1024


class PasswordPolicyError(ValueError):
    """Raised when a password does not satisfy the local-auth policy."""


@lru_cache(maxsize=1)
def _password_hasher() -> PasswordHash:
    return PasswordHash.recommended()


def normalize_password(password: str) -> str:
    """Normalize a password without trimming user-provided whitespace."""
    if not isinstance(password, str):
        raise PasswordPolicyError("Password must be text.")

    normalized = unicodedata.normalize("NFC", password)
    if len(normalized) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must contain at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(normalized) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must contain at most {MAX_PASSWORD_LENGTH} characters."
        )
    return normalized


def hash_password(password: str) -> str:
    """Return a self-contained Argon2id password hash."""
    return _password_hasher().hash(normalize_password(password))


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password, treating malformed input or hashes as a mismatch."""
    try:
        normalized = normalize_password(password)
        return _password_hasher().verify(normalized, password_hash)
    except (PasswordPolicyError, TypeError, ValueError):
        return False


def verify_and_update_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Verify a password and return a replacement hash when parameters changed."""
    try:
        normalized = normalize_password(password)
        valid, updated_hash = _password_hasher().verify_and_update(
            normalized,
            password_hash,
        )
        return valid, updated_hash
    except (PasswordPolicyError, TypeError, ValueError):
        return False, None


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """Return a process-stable hash for timing-safe unknown-user checks."""
    return _password_hasher().hash("asianode dummy password for timing checks")
