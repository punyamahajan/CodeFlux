from __future__ import annotations

import pytest

from codeflux.settings import Settings


def test_app_refuses_to_boot_with_default_secret_outside_test_env():
    # Outside ENV=test, empty or known default secrets must raise ValueError
    with pytest.raises(ValueError, match="Secret 'MASTER_KEY' must be set"):
        Settings(
            env="prod",
            master_key="",
            jwt_secret="some-real-jwt-secret",
            key_hmac_secret="some-real-hmac-secret",
        )

    with pytest.raises(ValueError, match="Secret 'MASTER_KEY' must be set"):
        Settings(
            env="prod",
            master_key="development-only-change-me",
            jwt_secret="some-real-jwt-secret",
            key_hmac_secret="some-real-hmac-secret",
        )

    with pytest.raises(ValueError, match="Secret 'JWT_SECRET' must be set"):
        Settings(
            env="prod",
            master_key="some-real-master-key-32-bytes!!",
            jwt_secret="secret",
            key_hmac_secret="some-real-hmac-secret",
        )

    with pytest.raises(ValueError, match="Secret 'KEY_HMAC_SECRET' must be set"):
        Settings(
            env="dev",
            master_key="some-real-master-key-32-bytes!!",
            jwt_secret="some-real-jwt-secret",
            key_hmac_secret="default",
        )


def test_valid_secrets_accepted_outside_test_env():
    settings = Settings(
        env="prod",
        master_key="real-master-key-production-ready!",
        jwt_secret="real-jwt-secret-production-ready!",
        key_hmac_secret="real-hmac-secret-production-ready!",
    )
    assert settings.master_key == "real-master-key-production-ready!"
    assert settings.jwt_secret == "real-jwt-secret-production-ready!"
    assert settings.key_hmac_secret == "real-hmac-secret-production-ready!"
    assert settings.master_secret == "real-master-key-production-ready!"


def test_throwaway_secrets_generated_in_test_env():
    settings = Settings(
        env="test",
        master_key="",
        jwt_secret="",
        key_hmac_secret="",
    )
    assert settings.master_key != ""
    assert settings.jwt_secret != ""
    assert settings.key_hmac_secret != ""
    assert settings.master_key != "development-only-change-me"
    assert settings.master_secret == settings.master_key
