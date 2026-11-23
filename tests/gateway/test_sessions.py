from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codeflux.app import create_app
from codeflux.db.models import (
    Organization,
    PlatformKey,
    RequestTrace,
    Session,
    SessionMessage,
    User,
)
from codeflux.db.session import get_db_session
from codeflux.schemas import Message
from codeflux.security.crypto import generate_platform_key, hash_platform_key
from codeflux.security.passwords import hash_password
from codeflux.security.tokens import create_access_token
from codeflux.sessions.service import count_tokens, trim_messages
from codeflux.settings import Settings


def test_count_tokens():
    assert count_tokens(None) == 1
    assert count_tokens("") == 1
    assert count_tokens("abcd") == 1
    assert count_tokens("a" * 40) == 10


def test_trim_messages_preserves_system_and_newest_turns():
    # Budget: 20 tokens (~80 chars)
    # Total input: system (5 tokens) + 5 messages of 10 tokens each = 55 tokens
    sys_msg = Message(role="system", content="s" * 20)  # 5 tokens
    m1 = Message(role="user", content="u" * 40)  # 10 tokens
    m2 = Message(role="assistant", content="a" * 40)  # 10 tokens
    m3 = Message(role="user", content="v" * 40)  # 10 tokens
    m4 = Message(role="assistant", content="b" * 40)  # 10 tokens
    m5 = Message(role="user", content="w" * 40)  # 10 tokens

    # Total 55 tokens, budget 25 tokens -> should keep sys_msg (5 tokens) + m4 (10 tokens) + m5 (10 tokens) = 25 tokens
    trimmed, count = trim_messages([sys_msg, m1, m2, m3, m4, m5], budget_tokens=25)
    assert count == 3
    assert len(trimmed) == 3
    assert trimmed[0].role == "system"
    assert trimmed[0].content == sys_msg.content
    assert trimmed[1].role == "assistant"
    assert trimmed[1].content == m4.content
    assert trimmed[2].role == "user"
    assert trimmed[2].content == m5.content


@pytest.fixture
async def session_test_app(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> AsyncIterator[FastAPI]:
    config_path = tmp_path / "routes.yaml"
    config_path.write_text(
        json.dumps(
            {
                "routes": {
                    "chat": {
                        "strategy": "priority",
                        "candidates": [
                            {"provider": "openai", "model": "gpt-4o-mini", "timeout_seconds": 10.0},
                            {
                                "provider": "groq",
                                "model": "llama-3.3-70b-versatile",
                                "timeout_seconds": 10.0,
                            },
                        ],
                    },
                    "low-budget-chat": {
                        "strategy": "priority",
                        "candidates": [
                            {"provider": "openai", "model": "gpt-4o-mini", "timeout_seconds": 10.0},
                        ],
                    },
                },
                "default_route": "chat",
            }
        )
    )

    credentials = {
        "openai_main": {"provider": "openai", "key": "test-openai-key"},
        "groq_main": {"provider": "groq", "key": "test-groq-key"},
    }

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
async def session_fixtures(db_session: AsyncSession) -> dict[str, Any]:
    settings = Settings(env="test")
    org = Organization(name="Session Test Org")
    db_session.add(org)
    await db_session.flush()

    user1 = User(
        org_id=org.id,
        email="alice@test.com",
        password_hash=hash_password("pw1"),
        role="member",
    )
    user2 = User(
        org_id=org.id,
        email="bob@test.com",
        password_hash=hash_password("pw2"),
        role="member",
    )
    admin = User(
        org_id=org.id,
        email="admin@test.com",
        password_hash=hash_password("pwadmin"),
        role="admin",
    )
    db_session.add_all([user1, user2, admin])
    await db_session.flush()

    raw_k1 = generate_platform_key()
    k1 = PlatformKey(
        org_id=org.id,
        user_id=user1.id,
        name="Key 1",
        key_prefix=raw_k1[:16],
        key_digest=hash_platform_key(raw_k1, settings.key_hmac_secret),
        credit_limit_micro=100_000_000,
        credit_remaining_micro=100_000_000,
        rpm_limit=60,
    )

    raw_k2 = generate_platform_key()
    k2 = PlatformKey(
        org_id=org.id,
        user_id=user2.id,
        name="Key 2",
        key_prefix=raw_k2[:16],
        key_digest=hash_platform_key(raw_k2, settings.key_hmac_secret),
        credit_limit_micro=100_000_000,
        credit_remaining_micro=100_000_000,
        rpm_limit=60,
    )
    db_session.add_all([k1, k2])
    await db_session.flush()

    token_user1 = create_access_token(
        {"sub": user1.id, "org_id": org.id, "role": user1.role}, secret=settings.jwt_secret
    )
    token_user2 = create_access_token(
        {"sub": user2.id, "org_id": org.id, "role": user2.role}, secret=settings.jwt_secret
    )
    token_admin = create_access_token(
        {"sub": admin.id, "org_id": org.id, "role": admin.role}, secret=settings.jwt_secret
    )

    return {
        "org": org,
        "user1": user1,
        "user2": user2,
        "admin": admin,
        "key1_raw": raw_k1,
        "key1_id": k1.id,
        "key2_raw": raw_k2,
        "key2_id": k2.id,
        "token_user1": token_user1,
        "token_user2": token_user2,
        "token_admin": token_admin,
    }


@pytest.mark.asyncio
async def test_stage_7_gate_session_failover_history_and_isolation(
    session_test_app: FastAPI, session_fixtures: dict[str, Any], db_session: AsyncSession
):
    """Stage 7 Gate:

    "a test sends request 1 to provider A, forces A down, sends only a short follow-up,
    and confirms provider B received the full earlier history; trimming keeps the newest turns;
    a different key cannot read the session."
    """
    transport = httpx.ASGITransport(app=session_test_app)
    session_id = "ses_gate_stage7"
    key1 = session_fixtures["key1_raw"]
    key2 = session_fixtures["key2_raw"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with respx.mock(assert_all_called=False) as respx_mock:
            # Setup Provider A (OpenAI)
            openai_route = respx_mock.post("https://api.openai.com/v1/chat/completions").respond(
                200,
                json={
                    "id": "chatcmpl-a1",
                    "object": "chat.completion",
                    "created": 1234567,
                    "model": "gpt-4o-mini",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "Acknowledged. Secret code is 42.",
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                },
            )

            # Setup Provider B (Groq)
            groq_route = respx_mock.post("https://api.groq.com/openai/v1/chat/completions").respond(
                200,
                json={
                    "id": "chatcmpl-b1",
                    "object": "chat.completion",
                    "created": 1234568,
                    "model": "llama-3.3-70b-versatile",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "Your secret code is 42.",
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 25, "completion_tokens": 8, "total_tokens": 33},
                },
            )

            # 1. Send Request 1 to Provider A with session header
            r1 = await client.post(
                "/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key1}",
                    "X-OmniKey-Session": session_id,
                },
                json={
                    "model": "chat",
                    "messages": [{"role": "user", "content": "My secret code is 42."}],
                },
            )
            assert r1.status_code == 200, r1.text
            assert openai_route.called
            assert not groq_route.called

            # Check trace facts for request 1
            stmt1 = (
                select(RequestTrace)
                .where(RequestTrace.org_id == session_fixtures["org"].id)
                .order_by(RequestTrace.created_at.desc())
            )
            async with session_test_app.state.session_factory() as s:
                res1 = await s.execute(stmt1)
                trace1 = res1.scalars().first()
            assert trace1 is not None
            assert trace1.facts["session_id"] == session_id
            assert trace1.facts["context_carried"] is False
            assert trace1.facts["provider_changed"] is False
            assert trace1.facts["messages_sent"] == 1

            # 2. Force Provider A down via demo outages
            session_test_app.state.demo_outages.add("openai")
            try:
                # 3. Send Request 2 with ONLY a short follow-up
                r2 = await client.post(
                    "/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key1}",
                        "X-OmniKey-Session": session_id,
                    },
                    json={
                        "model": "chat",
                        "messages": [{"role": "user", "content": "What is my secret code?"}],
                    },
                )
                assert r2.status_code == 200, r2.text
                assert groq_route.called

                # Confirm Provider B received the full earlier history!
                groq_request_payload = json.loads(groq_route.calls.last.request.content)
                groq_messages = groq_request_payload["messages"]
                assert len(groq_messages) == 3
                assert groq_messages[0] == {"role": "user", "content": "My secret code is 42."}
                assert groq_messages[1] == {
                    "role": "assistant",
                    "content": "Acknowledged. Secret code is 42.",
                }
                assert groq_messages[2] == {"role": "user", "content": "What is my secret code?"}
            finally:
                session_test_app.state.demo_outages.clear()

            # Check trace facts for request 2
            stmt2 = (
                select(RequestTrace)
                .where(RequestTrace.org_id == session_fixtures["org"].id)
                .order_by(RequestTrace.created_at.desc())
            )
            async with session_test_app.state.session_factory() as s:
                res2 = await s.execute(stmt2)
                trace2 = res2.scalars().first()
            assert trace2 is not None
            assert trace2.provider == "groq"
            assert trace2.facts["session_id"] == session_id
            assert trace2.facts["context_carried"] is True
            assert trace2.facts["provider_changed"] is True
            assert trace2.facts["messages_sent"] == 3
            assert trace2.facts["messages_trimmed"] == 0

            # 4. Confirm a different key cannot read the session!
            r3 = await client.post(
                "/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key2}",
                    "X-OmniKey-Session": session_id,
                },
                json={
                    "model": "chat",
                    "messages": [{"role": "user", "content": "Can I read this?"}],
                },
            )
            assert r3.status_code == 403, r3.text
            err = r3.json()
            assert "error" in err
            assert err["error"]["type"] == "permission_denied"
            assert "different key cannot read this session" in err["error"]["message"]


@pytest.mark.asyncio
async def test_session_trimming_gateway_integration(
    session_test_app: FastAPI, session_fixtures: dict[str, Any]
):
    """Test that trimming oldest turns keeps newest turns when context budget is exceeded."""
    transport = httpx.ASGITransport(app=session_test_app)
    session_id = "ses_trim_test"
    key1 = session_fixtures["key1_raw"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with respx.mock(assert_all_called=False) as respx_mock:
            openai_route = respx_mock.post("https://api.openai.com/v1/chat/completions").respond(
                200,
                json={
                    "id": "chatcmpl-trim",
                    "object": "chat.completion",
                    "created": 1234567,
                    "model": "gpt-4o-mini",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            )

            # Turn 1: System prompt + long turn 1
            r1 = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {key1}", "X-OmniKey-Session": session_id},
                json={
                    "model": "chat",
                    "messages": [
                        {"role": "system", "content": "SYSTEM_PROMPT"},
                        {"role": "user", "content": "TURN_1_" + ("x" * 12000)},  # 3000 tokens
                    ],
                },
            )
            assert r1.status_code == 200

            # Turn 2: Another long turn
            r2 = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {key1}", "X-OmniKey-Session": session_id},
                json={
                    "model": "chat",
                    "messages": [
                        {"role": "user", "content": "TURN_2_" + ("y" * 12000)},  # 3000 tokens
                    ],
                },
            )
            assert r2.status_code == 200

            # Turn 3: Short follow-up (total now exceeds default 6000 token budget)
            r3 = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {key1}", "X-OmniKey-Session": session_id},
                json={
                    "model": "chat",
                    "messages": [
                        {"role": "user", "content": "TURN_3_NEWEST"},
                    ],
                },
            )
            assert r3.status_code == 200

            # Inspect payload sent to upstream provider on turn 3
            sent_payload = json.loads(openai_route.calls.last.request.content)
            sent_messages = sent_payload["messages"]

            # Confirm newest turn is preserved and system prompt is preserved
            assert sent_messages[0]["role"] == "system"
            assert sent_messages[0]["content"] == "SYSTEM_PROMPT"
            assert sent_messages[-1]["role"] == "user"
            assert sent_messages[-1]["content"] == "TURN_3_NEWEST"
            # And oldest user turn 1 was trimmed!
            assert not any("TURN_1_" in m.get("content", "") for m in sent_messages)


@pytest.mark.asyncio
async def test_session_expiration_on_read(
    session_test_app: FastAPI, session_fixtures: dict[str, Any], db_session: AsyncSession
):
    """Test that sessions expire on read after 24 hours."""
    transport = httpx.ASGITransport(app=session_test_app)
    session_id = "ses_expired_24h"
    key1 = session_fixtures["key1_raw"]

    # 1. Create a session record directly in database that was last active 25 hours ago
    past = datetime.now(UTC) - timedelta(hours=25)
    expired_ses = Session(
        id=session_id,
        org_id=session_fixtures["org"].id,
        key_id=session_fixtures["key1_id"],
        created_at=past,
        last_active_at=past,
    )
    old_msg = SessionMessage(
        id="msg_old_1",
        org_id=session_fixtures["org"].id,
        session_id=session_id,
        role="user",
        content="Ancient secret",
        created_at=past,
    )
    db_session.add_all([expired_ses, old_msg])
    await db_session.flush()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 2. Member API GET /api/member/sessions/{id} returns 404 because session expired
        r_member = await client.get(
            f"/api/member/sessions/{session_id}",
            headers={"Authorization": f"Bearer {session_fixtures['token_user1']}"},
        )
        assert r_member.status_code == 404
        assert "expired" in r_member.json()["error"]["message"].lower()

        # 3. Gateway request with expired session starts fresh (purges old messages, doesn't send old secret)
        with respx.mock(assert_all_called=False) as respx_mock:
            openai_route = respx_mock.post("https://api.openai.com/v1/chat/completions").respond(
                200,
                json={
                    "id": "chatcmpl-fresh",
                    "object": "chat.completion",
                    "created": 1234567,
                    "model": "gpt-4o-mini",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                },
            )

            r_gw = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {key1}", "X-OmniKey-Session": session_id},
                json={"model": "chat", "messages": [{"role": "user", "content": "Hello"}]},
            )
            assert r_gw.status_code == 200
            sent_payload = json.loads(openai_route.calls.last.request.content)
            # Ancient secret was NOT sent because it expired!
            assert len(sent_payload["messages"]) == 1
            assert sent_payload["messages"][0]["content"] == "Hello"


@pytest.mark.asyncio
async def test_member_sessions_crud_and_pagination(
    session_test_app: FastAPI, session_fixtures: dict[str, Any]
):
    """Test member session endpoints: list, get detail, delete, and isolation."""
    transport = httpx.ASGITransport(app=session_test_app)
    key1 = session_fixtures["key1_raw"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with respx.mock(assert_all_called=False) as respx_mock:
            respx_mock.post("https://api.openai.com/v1/chat/completions").respond(
                200,
                json={
                    "id": "chatcmpl-mem",
                    "object": "chat.completion",
                    "created": 1234567,
                    "model": "gpt-4o-mini",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "reply"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                },
            )

            # Create session 1 and 2
            await client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {key1}", "X-OmniKey-Session": "ses_mem_1"},
                json={"model": "chat", "messages": [{"role": "user", "content": "turn 1"}]},
            )
            await client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {key1}", "X-OmniKey-Session": "ses_mem_2"},
                json={"model": "chat", "messages": [{"role": "user", "content": "turn 2"}]},
            )

        # 1. User 1 lists sessions
        r_list = await client.get(
            "/api/member/sessions",
            headers={"Authorization": f"Bearer {session_fixtures['token_user1']}"},
        )
        assert r_list.status_code == 200
        items = r_list.json()["items"]
        session_ids = [s["id"] for s in items]
        assert "ses_mem_1" in session_ids
        assert "ses_mem_2" in session_ids

        # 2. User 1 gets session detail
        r_detail = await client.get(
            "/api/member/sessions/ses_mem_1",
            headers={"Authorization": f"Bearer {session_fixtures['token_user1']}"},
        )
        assert r_detail.status_code == 200
        detail = r_detail.json()
        assert detail["id"] == "ses_mem_1"
        assert len(detail["messages"]) == 2
        assert detail["messages"][0]["role"] == "user"
        assert detail["messages"][1]["role"] == "assistant"

        # 3. User 2 cannot get User 1's session
        r_detail_unauth = await client.get(
            "/api/member/sessions/ses_mem_1",
            headers={"Authorization": f"Bearer {session_fixtures['token_user2']}"},
        )
        assert r_detail_unauth.status_code == 403

        # 4. Admin can get User 1's session
        r_detail_admin = await client.get(
            "/api/member/sessions/ses_mem_1",
            headers={"Authorization": f"Bearer {session_fixtures['token_admin']}"},
        )
        assert r_detail_admin.status_code == 200

        # 5. User 2 cannot delete User 1's session
        r_del_unauth = await client.delete(
            "/api/member/sessions/ses_mem_1",
            headers={"Authorization": f"Bearer {session_fixtures['token_user2']}"},
        )
        assert r_del_unauth.status_code == 403

        # 6. User 1 deletes User 1's session
        r_del = await client.delete(
            "/api/member/sessions/ses_mem_1",
            headers={"Authorization": f"Bearer {session_fixtures['token_user1']}"},
        )
        assert r_del.status_code == 200
        assert r_del.json()["deleted"] is True

        # Now GET returns 404
        r_after_del = await client.get(
            "/api/member/sessions/ses_mem_1",
            headers={"Authorization": f"Bearer {session_fixtures['token_user1']}"},
        )
        assert r_after_del.status_code == 404


@pytest.mark.asyncio
async def test_session_streaming_chat(session_test_app: FastAPI, session_fixtures: dict[str, Any]):
    """Test that streaming chat responses accumulate content into session history."""
    transport = httpx.ASGITransport(app=session_test_app)
    session_id = "ses_stream_test"
    key1 = session_fixtures["key1_raw"]

    stream_content = (
        'data: {"id":"chatcmpl-s","model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"Streamed "}}]}\n\n'
        'data: {"id":"chatcmpl-s","model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"answer."}}]}\n\n'
        'data: {"id":"chatcmpl-s","model":"gpt-4o-mini","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with respx.mock(assert_all_called=False) as respx_mock:
            respx_mock.post("https://api.openai.com/v1/chat/completions").respond(
                200,
                headers={"content-type": "text/event-stream"},
                content=stream_content,
            )

            # Turn 1: streaming
            resp1 = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {key1}", "X-OmniKey-Session": session_id},
                json={
                    "model": "chat",
                    "messages": [{"role": "user", "content": "Tell me a word"}],
                    "stream": True,
                },
            )
            assert resp1.status_code == 200
            # Read full stream
            body = resp1.text
            assert "Streamed" in body

        # Check that session detail shows the full accumulated assistant answer
        resp_detail = await client.get(
            f"/api/member/sessions/{session_id}",
            headers={"Authorization": f"Bearer {session_fixtures['token_user1']}"},
        )
        assert resp_detail.status_code == 200
        detail = resp_detail.json()
        assert len(detail["messages"]) == 2
        assert detail["messages"][0]["role"] == "user"
        assert detail["messages"][1]["role"] == "assistant"
        assert detail["messages"][1]["content"] == "Streamed answer."
