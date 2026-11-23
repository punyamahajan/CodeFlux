"""Tests for Stage 9: Playground, Compare Arena, and Debate Arena."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codeflux.app import create_app
from codeflux.db.models import Organization, PlatformKey, User
from codeflux.db.session import get_db_session
from codeflux.security.crypto import generate_platform_key, hash_platform_key
from codeflux.security.passwords import hash_password
from codeflux.security.tokens import create_access_token
from codeflux.settings import Settings


@pytest.fixture
async def arena_app(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> FastAPI:
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
                    "claude-fast": {
                        "candidates": [
                            {"provider": "openai", "model": "gpt-4o-mini", "timeout_seconds": 10.0}
                        ]
                    },
                },
                "default_route": "default",
            }
        )
    )
    credentials = {"openai_main": {"provider": "openai", "key": "test-key"}}
    settings = Settings(
        env="test",
        config_path=config_path,
        credentials_json=json.dumps(credentials),
    )
    app = create_app(settings)
    app.state.session_factory = session_factory

    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def arena_data(db_session: AsyncSession) -> dict[str, Any]:
    settings = Settings(env="test")
    org = Organization(name="Arena Test Org")
    db_session.add(org)
    await db_session.flush()

    user = User(
        org_id=org.id,
        email="tester@arena.com",
        password_hash=hash_password("pw1234567"),
        role="admin",
    )
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_platform_key()
    digest = hash_platform_key(raw_key, settings.key_hmac_secret)
    pk = PlatformKey(
        org_id=org.id,
        user_id=user.id,
        name="Arena Key",
        key_prefix=raw_key[:16],
        key_digest=digest,
        credit_limit_micro=50_000_000,
        credit_remaining_micro=50_000_000,
        rpm_limit=60,
    )
    db_session.add(pk)
    await db_session.flush()

    token = create_access_token(
        {"sub": user.id, "org_id": org.id, "role": "admin"}, secret=settings.jwt_secret
    )

    return {
        "org_id": org.id,
        "user_id": user.id,
        "token": token,
        "raw_key": raw_key,
        "pk_id": pk.id,
    }


# ---------------------------------------------------------------------------
# 1. Playground
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_playground_chat_openai_format(arena_app: FastAPI, arena_data: dict[str, Any]):
    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.openai.com/v1/chat/completions").return_value = httpx.Response(
            200,
            json={
                "id": "chatcmpl-play",
                "object": "chat.completion",
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello from playground!"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            },
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=arena_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/playground/chat",
                headers={"Authorization": f"Bearer {arena_data['token']}"},
                json={
                    "format": "openai",
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "hi"}],
                    "key_id": arena_data["pk_id"],
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "Hello from playground!"
    assert "raw_request" in data
    assert "raw_response" in data
    assert data["tokens"]["total_tokens"] == 20
    assert "trace_id" in data

    # Verify explain endpoint returns valid output for this playground trace
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=arena_app), base_url="http://test"
    ) as client:
        explain_resp = await client.get(
            f"/api/explain/trace/{data['trace_id']}",
            headers={"Authorization": f"Bearer {arena_data['token']}"},
        )
    assert explain_resp.status_code == 200
    explain_data = explain_resp.json()
    assert "headline" in explain_data
    assert "bullets" in explain_data


@pytest.mark.asyncio
async def test_playground_chat_gemini_format(arena_app: FastAPI, arena_data: dict[str, Any]):
    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.openai.com/v1/chat/completions").return_value = httpx.Response(
            200,
            json={
                "id": "chatcmpl-play-gem",
                "object": "chat.completion",
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Gemini format response"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            },
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=arena_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/playground/chat",
                headers={"Authorization": f"Bearer {arena_data['token']}"},
                json={
                    "format": "gemini",
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "hello"}],
                    "key_id": arena_data["pk_id"],
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "Gemini format response"
    assert "candidates" in data["raw_response"]


# ---------------------------------------------------------------------------
# 2. Compare Arena
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_partial_results_on_error(arena_app: FastAPI, arena_data: dict[str, Any]):
    """Compare must return partial results when one model fails."""
    call_count = 0

    def mock_route(request: httpx.Request):
        nonlocal call_count
        call_count += 1
        body = json.loads(request.content)
        # Fail if model starts with fail
        if "fail" in body.get("model", ""):
            return httpx.Response(500, json={"error": "provider down"})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-cmp",
                "object": "chat.completion",
                "model": body.get("model"),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"Reply from {body.get('model')}",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.openai.com/v1/chat/completions").mock(side_effect=mock_route)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=arena_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/arena/compare",
                headers={"Authorization": f"Bearer {arena_data['token']}"},
                json={
                    "prompt": "Compare this",
                    "models": ["gpt-4o-mini", "fail-model"],
                    "judge": False,
                    "key_id": arena_data["pk_id"],
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["models"]) == 2
    ok_res = next(m for m in data["models"] if m["model"] == "gpt-4o-mini")
    fail_res = next(m for m in data["models"] if m["model"] == "fail-model")
    assert ok_res["output"] == "Reply from gpt-4o-mini"
    assert ok_res["error"] is None
    assert fail_res["output"] is None
    assert fail_res["error"] is not None
    assert "gpt-4o-mini" in data["ranking"]
    assert "fail-model" not in data["ranking"]


@pytest.mark.asyncio
async def test_compare_deterministic_ranking_with_judge(
    arena_app: FastAPI, arena_data: dict[str, Any]
):
    """Ranking must be deterministic for fixed scores."""
    judge_reply = json.dumps(
        {
            "scores": {
                "model-b": {
                    "accuracy": 10,
                    "clarity": 10,
                    "completeness": 10,
                    "reason": "Exceptional",
                },
                "model-a": {"accuracy": 8, "clarity": 8, "completeness": 8, "reason": "Good"},
            }
        }
    )

    def mock_route(request: httpx.Request):
        body = json.loads(request.content)
        messages = body.get("messages", [])
        if any("judge" in m.get("content", "").lower() for m in messages):
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"role": "assistant", "content": judge_reply}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": f"Output for {body.get('model')}"}}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.openai.com/v1/chat/completions").mock(side_effect=mock_route)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=arena_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/arena/compare",
                headers={"Authorization": f"Bearer {arena_data['token']}"},
                json={
                    "prompt": "Explain gravity",
                    "models": ["model-a", "model-b"],
                    "judge": True,
                    "key_id": arena_data["pk_id"],
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ranking"] == ["model-b", "model-a"]  # model-b scored 30 vs model-a 24

    # Check explain endpoint for compare
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=arena_app), base_url="http://test"
    ) as client:
        explain_resp = await client.get(
            f"/api/explain/compare/{data['run_id']}",
            headers={"Authorization": f"Bearer {arena_data['token']}"},
        )
    assert explain_resp.status_code == 200
    explain_data = explain_resp.json()
    assert "headline" in explain_data
    assert "bullets" in explain_data


@pytest.mark.asyncio
async def test_compare_invalid_judge_degrades_gracefully(
    arena_app: FastAPI, arena_data: dict[str, Any]
):
    """Judge returning invalid JSON degrades gracefully with judge_flagged=True."""

    def mock_route(request: httpx.Request):
        body = json.loads(request.content)
        messages = body.get("messages", [])
        if any("judge" in m.get("content", "").lower() for m in messages):
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": "I am not returning JSON"}}
                    ],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": f"Output for {body.get('model')}"}}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.openai.com/v1/chat/completions").mock(side_effect=mock_route)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=arena_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/arena/compare",
                headers={"Authorization": f"Bearer {arena_data['token']}"},
                json={
                    "prompt": "Test invalid judge",
                    "models": ["model-a", "model-b"],
                    "judge": True,
                    "key_id": arena_data["pk_id"],
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["judge_flagged"] is True
    assert len(data["ranking"]) == 2  # Still ranked based on tie-breaks


# ---------------------------------------------------------------------------
# 3. Debate Arena
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_debate_rounds_and_caps(arena_app: FastAPI, arena_data: dict[str, Any]):
    """Debate must respect round caps, word caps (<= 120 words), and judge properly."""
    long_speech = "word " * 150  # 150 words to test 120 word cap
    judge_reply = json.dumps(
        {
            "score_for": {
                "argument_strength": 9,
                "evidence": 9,
                "rebuttal": 8,
                "reason": "Persuasive",
            },
            "score_against": {
                "argument_strength": 7,
                "evidence": 6,
                "rebuttal": 7,
                "reason": "Adequate",
            },
        }
    )

    def mock_route(request: httpx.Request):
        body = json.loads(request.content)
        messages = body.get("messages", [])
        if any("judge" in m.get("content", "").lower() for m in messages):
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"role": "assistant", "content": judge_reply}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": long_speech}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 120, "total_tokens": 170},
            },
        )

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.openai.com/v1/chat/completions").mock(side_effect=mock_route)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=arena_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/arena/debate",
                headers={"Authorization": f"Bearer {arena_data['token']}"},
                json={
                    "topic": "Is AI safe?",
                    "model_a": "pro-ai",
                    "model_b": "con-ai",
                    "rounds": 2,
                    "key_id": arena_data["pk_id"],
                },
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["rounds"] == 2
    # 2 rounds * 2 sides = 4 turns
    assert len(data["turns"]) == 4
    for turn in data["turns"]:
        assert turn["word_count"] <= 120
    assert data["verdict"] == "FOR"
    assert data["score_a"] == 26
    assert data["score_b"] == 20

    # Verify explain endpoint for debate
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=arena_app), base_url="http://test"
    ) as client:
        explain_resp = await client.get(
            f"/api/explain/debate/{data['run_id']}",
            headers={"Authorization": f"Bearer {arena_data['token']}"},
        )
    assert explain_resp.status_code == 200
    explain_data = explain_resp.json()
    assert "headline" in explain_data
    assert "FOR" in explain_data["headline"]
