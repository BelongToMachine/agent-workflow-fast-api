import pytest

from app.core.passwords import (
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    normalize_password,
    verify_and_update_password,
    verify_password,
)


def test_passwords_are_nfc_normalized_before_hashing() -> None:
    composed = "é" + "safe password!"
    decomposed = "e\u0301" + "safe password!"
    composed_hash = hash_password(composed)

    assert normalize_password(decomposed) == composed
    assert verify_password(decomposed, composed_hash) is True


def test_password_hashes_use_argon2id_and_reject_mismatches() -> None:
    password = "a secure password with enough length"
    password_hash = hash_password(password)

    assert password_hash.startswith("$argon2id$")
    assert verify_password(password, password_hash) is True
    assert verify_password("a different password with enough length", password_hash) is False


def test_password_policy_requires_at_least_twelve_characters() -> None:
    with pytest.raises(PasswordPolicyError, match=str(MIN_PASSWORD_LENGTH)):
        hash_password("too short")


def test_password_policy_accepts_twelve_characters() -> None:
    password_hash = hash_password("a" * MIN_PASSWORD_LENGTH)

    assert verify_password("a" * MIN_PASSWORD_LENGTH, password_hash) is True


def test_verify_and_update_returns_no_replacement_for_current_parameters() -> None:
    password_hash = hash_password("a secure password with enough length")

    valid, replacement = verify_and_update_password(
        "a secure password with enough length",
        password_hash,
    )

    assert valid is True
    assert replacement is None
