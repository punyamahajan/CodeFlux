from __future__ import annotations

import pytest
from cryptography.fernet import InvalidToken

from codeflux.security.crypto import (
    PLATFORM_KEY_PREFIX,
    decrypt_provider_key,
    encrypt_provider_key,
    generate_platform_key,
    hash_platform_key,
    verify_platform_key,
)


def test_encrypt_decrypt_round_trip():
    master_key = "test-master-key-32-bytes-long!!"
    plain = "sk-proj-1234567890abcdef"

    encrypted = encrypt_provider_key(plain, master_key)
    assert encrypted != plain
    decrypted = decrypt_provider_key(encrypted, master_key)
    assert decrypted == plain


def test_tampered_ciphertext_rejected():
    master_key = "test-master-key-32-bytes-long!!"
    plain = "sk-proj-test-key"

    encrypted = encrypt_provider_key(plain, master_key)
    # Tamper with the ciphertext by flipping a character in the middle
    tampered = encrypted[:10] + ("A" if encrypted[10] != "A" else "B") + encrypted[11:]

    with pytest.raises(InvalidToken):
        decrypt_provider_key(tampered, master_key)


def test_hash_deterministic_and_different_from_plaintext():
    secret = "hmac-secret-key-123"
    key = "ok_live_test_key_sample"

    h1 = hash_platform_key(key, secret)
    h2 = hash_platform_key(key, secret)

    # Deterministic
    assert h1 == h2
    # Different from plaintext
    assert h1 != key
    # 64-character hexadecimal SHA-256
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)


def test_generated_keys_unique():
    keys = [generate_platform_key() for _ in range(1000)]
    assert len(keys) == 1000
    assert len(set(keys)) == 1000
    for k in keys:
        assert k.startswith(PLATFORM_KEY_PREFIX)
        assert len(k) > len(PLATFORM_KEY_PREFIX) + 20


def test_constant_time_verify():
    secret = "hmac-secret-xyz"
    key = generate_platform_key()
    key_hash = hash_platform_key(key, secret)

    assert verify_platform_key(key, key_hash, secret) is True
    assert verify_platform_key("ok_live_wrong_key", key_hash, secret) is False
    assert verify_platform_key(key, "a" * 64, secret) is False
