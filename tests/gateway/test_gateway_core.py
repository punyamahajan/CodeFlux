from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.app import create_app
from codeflux.db.models import Organization, PlatformKey, User
from codeflux.db.session import get_db_session
from codeflux.security.crypto import generate_platform_key, hash_platform_key
from codeflux.settings import Settings


@pytest.fixture
async def gateway_app(db_session: AsyncSession, tmp_path: Path) -> AsyncIterator[FastAPI]:
    config_path = tmp_path / "routes.yaml"
    config_path.write_text(
        json.dumps(
            {
                "routes": {
                    "default": {
                        "candidates": [
                            {"provider": "openai", "model": "gpt-4o-mini", "timeout_seconds": 10.0}
                        ]
                    },
                    "gemini-flash": {
                        "candidates": [
                            {
                                "provider": "gemini",
                                "model": "gemini-2.0-flash",
                                "timeout_seconds": 10.0,
                            }
                        ]
                    },
                },
                "default_route": "default",
            }
        )
    )

    credentials = {
        "openai_main": {"provider": "openai", "key": "test-openai-key"},
        "gemini_main": {"provider": "gemini", "key": "test-gemini-key"},
    }

    settings = Settings(
        env="test",
        config_path=config_path,
        cors_origins="http://example.com,http://localhost:3000",
        credentials_json=json.dumps(credentials),
    )
    app = create_app(settings)

    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def platform_keys(db_session: AsyncSession) -> dict[str, str]:
    settings = Settings(env="test")
    # Create org and user
    org = Organization(name="Gateway Test Org")
    db_session.add(org)
    await db_session.flush()

    user = User(
        org_id=org.id,
        email="dev@gateway.com",
        password_hash="pw",
        role="member",
    )
    db_session.add(user)
    await db_session.flush()

    # 1. Valid active key with credits and RPM limit 2
    raw_valid = generate_platform_key()
    digest_valid = hash_platform_key(raw_valid, settings.key_hmac_secret)
    key_valid = PlatformKey(
        org_id=org.id,
        user_id=user.id,
        name="Valid Key",
        key_prefix=raw_valid[:16],
        key_digest=digest_valid,
        credit_limit_micro=100_000_000,
        credit_remaining_micro=100_000_000,
        rpm_limit=2,
    )

    # 2. Revoked key
    raw_revoked = generate_platform_key()
    digest_revoked = hash_platform_key(raw_revoked, settings.key_hmac_secret)
    key_revoked = PlatformKey(
        org_id=org.id,
        user_id=user.id,
        name="Revoked Key",
        key_prefix=raw_revoked[:16],
        key_digest=digest_revoked,
        credit_limit_micro=100_000_000,
        credit_remaining_micro=100_000_000,
        rpm_limit=60,
        revoked_at=datetime.now(UTC),
    )

    # 3. Expired key
    raw_expired = generate_platform_key()
    digest_expired = hash_platform_key(raw_expired, settings.key_hmac_secret)
    key_expired = PlatformKey(
        org_id=org.id,
        user_id=user.id,
        name="Expired Key",
        key_prefix=raw_expired[:16],
        key_digest=digest_expired,
        credit_limit_micro=100_000_000,
        credit_remaining_micro=100_000_000,
        rpm_limit=60,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )

    # 4. Zero credit key
    raw_zero = generate_platform_key()
    digest_zero = hash_platform_key(raw_zero, settings.key_hmac_secret)
    key_zero = PlatformKey(
        org_id=org.id,
        user_id=user.id,
        name="Zero Credit Key",
        key_prefix=raw_zero[:16],
        key_digest=digest_zero,
        credit_limit_micro=10_000_000,
        credit_remaining_micro=0,
        rpm_limit=60,
    )

    db_session.add_all([key_valid, key_revoked, key_expired, key_zero])
    await db_session.flush()

    return {
        "valid": raw_valid,
        "revoked": raw_revoked,
        "expired": raw_expired,
        "zero": raw_zero,
    }


@pytest.mark.asyncio
async def test_auth_rejections_use_openai_error_envelope(
    gateway_app: FastAPI, platform_keys: dict[str, str]
):
    transport = httpx.ASGITransport(app=gateway_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unknown key -> 401
        resp_unknown = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer ok_live_unknown_12345"},
            json={"model": "default", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp_unknown.status_code == 401
        data_unknown = resp_unknown.json()
        assert "error" in data_unknown
        assert data_unknown["error"]["type"] == "invalid_api_key"
        assert data_unknown["error"]["code"] == 401

        # 2. Revoked key -> 401
        resp_revoked = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {platform_keys['revoked']}"},
            json={"model": "default", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp_revoked.status_code == 401
        assert "revoked" in resp_revoked.json()["error"]["message"]

        # 3. Expired key -> 401
        resp_expired = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {platform_keys['expired']}"},
            json={"model": "default", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp_expired.status_code == 401
        assert "expired" in resp_expired.json()["error"]["message"]

        # 4. Zero credit key -> 429 insufficient_credits
        resp_zero = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {platform_keys['zero']}"},
            json={"model": "default", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp_zero.status_code == 429
        data_zero = resp_zero.json()
        assert data_zero["error"]["code"] == "insufficient_credits"
        assert data_zero["error"]["type"] == "insufficient_quota"


@pytest.mark.asyncio
async def test_rpm_limiter_returns_429_with_retry_after(
    gateway_app: FastAPI, platform_keys: dict[str, str]
):
    transport = httpx.ASGITransport(app=gateway_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {platform_keys['valid']}"}
        payload = {"model": "default", "messages": [{"role": "user", "content": "hi"}]}

        with respx.mock(assert_all_called=False) as respx_mock:
            respx_mock.post("https://api.openai.com/v1/chat/completions").respond(
                200,
                json={
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 1234567,
                    "model": "gpt-4o-mini",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                },
            )

            # Request 1: allowed (valid key has rpm_limit=2)
            r1 = await client.post("/v1/chat/completions", headers=headers, json=payload)
            assert r1.status_code == 200

            # Request 2: allowed
            r2 = await client.post("/v1/chat/completions", headers=headers, json=payload)
            assert r2.status_code == 200

            # Request 3: rejected with 429
            r3 = await client.post("/v1/chat/completions", headers=headers, json=payload)
            assert r3.status_code == 429
            assert "Retry-After" in r3.headers
            assert int(r3.headers["Retry-After"]) >= 1
            data = r3.json()
            assert "error" in data
            assert data["error"]["type"] == "requests"


@pytest.mark.asyncio
async def test_respx_non_stream_and_usage_estimation(
    gateway_app: FastAPI, platform_keys: dict[str, str]
):
    transport = httpx.ASGITransport(app=gateway_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {platform_keys['valid']}"}

        # Test case: provider returns no usage, gateway estimates chars // 4
        with respx.mock(assert_all_called=False) as respx_mock:
            respx_mock.post("https://api.openai.com/v1/chat/completions").respond(
                200,
                json={
                    "id": "chatcmpl-est",
                    "model": "gpt-4o-mini",
                    "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": "12345678"}}
                    ],
                },
            )

            resp = await client.post(
                "/v1/chat/completions",
                headers=headers,
                json={"model": "default", "messages": [{"role": "user", "content": "12345678"}]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["choices"][0]["message"]["content"] == "12345678"
            usage = data["usage"]
            assert usage["total_tokens"] > 0
            assert usage.get("estimated") is True


@pytest.mark.asyncio
async def test_respx_stream_and_empty_choices_final_chunk(
    gateway_app: FastAPI, platform_keys: dict[str, str]
):
    transport = httpx.ASGITransport(app=gateway_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"x-api-key": platform_keys["valid"]}

        # Stream response with final chunk having choices: []
        stream_content = (
            'data: {"id":"chatcmpl-s","model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"hello"}}]}\n\n'
            'data: {"id":"chatcmpl-s","model":"gpt-4o-mini","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            'data: {"id":"chatcmpl-s","model":"gpt-4o-mini","choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}\n\n'
            "data: [DONE]\n\n"
        )

        with respx.mock(assert_all_called=False) as respx_mock:
            respx_mock.post("https://api.openai.com/v1/chat/completions").respond(
                200,
                headers={"Content-Type": "text/event-stream"},
                text=stream_content,
            )

            resp = await client.post(
                "/v1/chat/completions",
                headers=headers,
                json={
                    "model": "default",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                },
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            text = resp.text
            assert "data: " in text
            assert "[DONE]" in text
            assert "hello" in text


@pytest.mark.asyncio
async def test_gemini_shaped_output_on_v1beta_with_query_param(
    gateway_app: FastAPI, platform_keys: dict[str, str]
):
    transport = httpx.ASGITransport(app=gateway_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Calls /v1beta/models/...:generateContent?key=...
        with respx.mock(assert_all_called=False) as respx_mock:
            respx_mock.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
            ).respond(
                200,
                json={
                    "candidates": [
                        {
                            "content": {"parts": [{"text": "Hello from Gemini!"}], "role": "model"},
                            "finishReason": "STOP",
                            "index": 0,
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 8,
                        "candidatesTokenCount": 5,
                        "totalTokenCount": 13,
                    },
                },
            )

            resp = await client.post(
                f"/v1beta/models/gemini-flash:generateContent?key={platform_keys['valid']}",
                json={
                    "contents": [{"parts": [{"text": "Hello"}], "role": "user"}],
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "candidates" in data
            assert data["candidates"][0]["content"]["parts"][0]["text"] == "Hello from Gemini!"
            assert data["candidates"][0]["finishReason"] == "STOP"
            assert "usageMetadata" in data
            assert data["usageMetadata"]["totalTokenCount"] == 13


@pytest.mark.asyncio
async def test_get_models_list(gateway_app: FastAPI, platform_keys: dict[str, str]):
    transport = httpx.ASGITransport(app=gateway_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {platform_keys['valid']}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        model_ids = [m["id"] for m in data["data"]]
        assert "default" in model_ids
