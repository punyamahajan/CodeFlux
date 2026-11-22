from __future__ import annotations

from codeflux.security.passwords import hash_password, verify_password


def test_hash_and_verify_password():
    password = "SuperSecretPassword123!"

    hashed = hash_password(password)
    assert hashed != password
    assert hashed.startswith("$argon2id$")

    # Correct password succeeds
    assert verify_password(password, hashed) is True

    # Wrong password rejected
    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password("supersecretpassword123!", hashed) is False  # Case sensitivity


def test_malformed_hash_rejected():
    assert verify_password("test", "invalid_not_an_argon_hash") is False
