from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from codeflux.security.tokens import (
    DEFAULT_TOKEN_EXPIRE_HOURS,
    create_access_token,
    decode_access_token,
)


def test_create_and_decode_token():
    secret = "jwt-secret-for-testing-123456789012"
    data = {"sub": "usr_test123", "org_id": "org_abc456", "role": "admin"}

    token = create_access_token(data, secret)
    payload = decode_access_token(token, secret)

    assert payload["sub"] == "usr_test123"
    assert payload["org_id"] == "org_abc456"
    assert payload["role"] == "admin"
    assert "iat" in payload
    assert "exp" in payload

    # Default lifetime is 12 hours
    exp_dt = datetime.fromtimestamp(payload["exp"], tz=UTC)
    iat_dt = datetime.fromtimestamp(payload["iat"], tz=UTC)
    diff = exp_dt - iat_dt
    assert abs(diff.total_seconds() - (DEFAULT_TOKEN_EXPIRE_HOURS * 3600)) < 5


def test_expired_jwt_rejected():
    secret = "jwt-secret-for-testing-123456789012"
    data = {"sub": "usr_expired", "org_id": "org_test", "role": "member"}

    # Created with negative expiry
    token = create_access_token(data, secret, expires_delta=timedelta(seconds=-10))

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token, secret)


def test_invalid_signature_rejected():
    secret1 = "secret-number-one-with-32-chars-ok!!"
    secret2 = "secret-number-two-with-32-chars-ok!!"
    data = {"sub": "usr_test", "org_id": "org_test", "role": "member"}

    token = create_access_token(data, secret1)

    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(token, secret2)


def test_tampered_token_rejected():
    secret = "jwt-secret-for-testing-32-bytes-long!"
    token = create_access_token({"sub": "usr_test"}, secret)

    tampered = token[:-4] + "xxxx"
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(tampered, secret)
