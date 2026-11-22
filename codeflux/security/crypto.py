from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet

PLATFORM_KEY_PREFIX = "ok_live_"


def _normalize_fernet_key(key: str | bytes) -> bytes:
    """Ensure key is a 32-byte urlsafe base64-encoded key acceptable by Fernet.

    If key is already 32 urlsafe-base64 bytes (44 chars), use it directly.
    Otherwise, derive a 32-byte key via SHA-256 and urlsafe base64 encode it.
    """
    key_bytes = key.encode("utf-8") if isinstance(key, str) else key
    try:
        decoded = base64.urlsafe_b64decode(key_bytes)
        if len(decoded) == 32:
            return key_bytes
    except (ValueError, binascii.Error):
        pass
    digest = hashlib.sha256(key_bytes).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_provider_key(plaintext: str, master_key: str | bytes) -> str:
    """Encrypt a provider key with Fernet using master_key."""
    fernet_key = _normalize_fernet_key(master_key)
    f = Fernet(fernet_key)
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_provider_key(ciphertext: str, master_key: str | bytes) -> str:
    """Decrypt a provider key with Fernet using master_key.

    Raises cryptography.fernet.InvalidToken if ciphertext is tampered with or invalid.
    """
    fernet_key = _normalize_fernet_key(master_key)
    f = Fernet(fernet_key)
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def generate_platform_key() -> str:
    """Generate a platform key with prefix 'ok_live_' plus 32 random url-safe bytes."""
    random_bytes = secrets.token_urlsafe(32)
    return f"{PLATFORM_KEY_PREFIX}{random_bytes}"


def hash_platform_key(key: str, hmac_secret: str | bytes) -> str:
    """Compute HMAC-SHA256 hex digest of a platform key using KEY_HMAC_SECRET."""
    secret_bytes = hmac_secret.encode("utf-8") if isinstance(hmac_secret, str) else hmac_secret
    return hmac.new(secret_bytes, key.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_platform_key(key: str, expected_hash: str, hmac_secret: str | bytes) -> bool:
    """Constant-time verification of a platform key against stored HMAC-SHA256 hash."""
    computed_hash = hash_platform_key(key, hmac_secret)
    return hmac.compare_digest(computed_hash, expected_hash)
