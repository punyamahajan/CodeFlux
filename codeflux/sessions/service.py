from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codeflux.api.schemas import (
    SessionDetailResponse,
    SessionItem,
    SessionMessageItem,
    decode_cursor,
    encode_cursor,
)
from codeflux.db.models import PlatformKey, Session, SessionMessage, generate_id
from codeflux.metering.pricing import get_context_budget
from codeflux.schemas import Message

logger = logging.getLogger("codeflux.sessions")

EXPIRY_WINDOW = timedelta(hours=24)


@asynccontextmanager
async def _get_session(session_or_factory: AsyncSession | async_sessionmaker[AsyncSession]):
    if isinstance(session_or_factory, AsyncSession):
        yield session_or_factory
    else:
        async with session_or_factory() as s:
            yield s


@dataclass
class SessionMeta:
    session_id: str
    context_carried: bool
    messages_sent: int
    messages_trimmed: int
    last_provider: str | None
    new_incoming_messages: list[Message]


def count_tokens(content: str | list[dict[str, Any]] | None) -> int:
    """Approximate token count as characters divided by 4 (minimum 1)."""
    if not content:
        return 1
    if isinstance(content, str):
        return max(1, len(content) // 4)
    return max(1, len(str(content)) // 4)


def trim_messages(messages: list[Message], budget_tokens: int) -> tuple[list[Message], int]:
    """Trim oldest turns to candidate's budget while keeping newest turns.

    Preserves system message at index 0 if present and possible.
    """
    if not messages:
        return [], 0

    total_tokens = sum(count_tokens(m.content) for m in messages)
    if total_tokens <= budget_tokens:
        return list(messages), 0

    has_system = messages[0].role == "system"
    system_msg = messages[0] if has_system else None
    working = list(messages[1:] if has_system else messages)

    system_tokens = count_tokens(system_msg.content) if system_msg else 0

    # Drop oldest turns from working list until within budget
    while (
        len(working) > 1
        and (system_tokens + sum(count_tokens(m.content) for m in working)) > budget_tokens
    ):
        working.pop(0)

    # If even system + latest message exceeds budget, decide between keeping latest or system
    if (
        system_msg
        and (system_tokens + sum(count_tokens(m.content) for m in working)) > budget_tokens
    ):
        result = [working[-1]] if working else [system_msg]
    elif system_msg:
        result = [system_msg] + working
    else:
        result = working

    trimmed_count = len(messages) - len(result)
    return result, trimmed_count


async def get_or_create_gateway_session(
    session_or_factory: AsyncSession | async_sessionmaker[AsyncSession],
    org_id: str,
    key_id: str | None,
    session_id: str,
) -> tuple[Session | None, str | None]:
    """Look up an existing session or create it on first use.

    Enforces 24-hour expiration on read and ensures a different key cannot read the session.
    """
    now = datetime.now(UTC)
    async with _get_session(session_or_factory) as session:
        stmt = select(Session).where(Session.id == session_id)
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()

        if record is not None:
            # 1. Check expiration on read (24 hours)
            if now - record.last_active_at > EXPIRY_WINDOW:
                # Expired: purge old session and messages
                await session.execute(
                    delete(SessionMessage).where(SessionMessage.session_id == session_id)
                )
                await session.delete(record)
                await session.flush()
                record = None
            else:
                # 2. Check tenant and key scope
                if record.org_id != org_id:
                    return None, f"session '{session_id}' not found in this organization"
                if key_id and record.key_id != key_id:
                    return None, "different key cannot read this session"

                # Update last active
                record.last_active_at = now
                await session.flush()
                return record, None

        # 3. Create fresh session on first use
        effective_key_id = key_id or "key_default"
        # Validate that key exists if a key_id was specified
        if key_id:
            key_record = await session.get(PlatformKey, key_id)
            if not key_record:
                # If key doesn't exist, we fallback to default key reference
                effective_key_id = key_id

        new_session = Session(
            id=session_id,
            org_id=org_id,
            key_id=effective_key_id,
            created_at=now,
            last_active_at=now,
        )
        session.add(new_session)
        await session.flush()
        return new_session, None


async def prepare_session_messages(
    session_or_factory: AsyncSession | async_sessionmaker[AsyncSession],
    session_id: str,
    incoming_messages: list[Message],
    model: str,
) -> tuple[list[Message], SessionMeta]:
    """Load stored messages, append incoming ones, and trim to model context budget."""
    async with _get_session(session_or_factory) as session:
        stmt = (
            select(SessionMessage)
            .where(SessionMessage.session_id == session_id)
            .order_by(SessionMessage.created_at.asc())
        )
        res = await session.execute(stmt)
        db_messages = list(res.scalars().all())

    # Find the last provider used from historical assistant messages
    last_provider: str | None = None
    for msg in reversed(db_messages):
        if msg.role == "assistant" and msg.metadata_json and "provider" in msg.metadata_json:
            last_provider = msg.metadata_json["provider"]
            break

    # Convert stored DB messages to Message objects
    history_messages = [Message(role=msg.role, content=msg.content) for msg in db_messages]

    # Check if incoming messages already contain history
    if len(incoming_messages) > len(history_messages) and history_messages:
        matches = True
        for h, inc in zip(history_messages, incoming_messages):
            if h.role != inc.role or h.content != inc.content:
                matches = False
                break
        if matches:
            all_messages = list(incoming_messages)
            new_incoming = list(incoming_messages[len(history_messages) :])
        else:
            all_messages = history_messages + list(incoming_messages)
            new_incoming = list(incoming_messages)
    elif (
        incoming_messages
        and history_messages
        and incoming_messages[0].role == "system"
        and history_messages[0].role == "system"
    ):
        if incoming_messages[0].content == history_messages[0].content:
            new_incoming = list(incoming_messages[1:])
            all_messages = history_messages + new_incoming
        else:
            new_incoming = list(incoming_messages)
            all_messages = (
                [incoming_messages[0]]
                + [m for m in history_messages if m.role != "system"]
                + list(incoming_messages[1:])
            )
    else:
        new_incoming = list(incoming_messages)
        all_messages = history_messages + list(incoming_messages)

    budget = get_context_budget(model)
    trimmed_messages, messages_trimmed = trim_messages(all_messages, budget)

    context_carried = len(history_messages) > 0 and any(
        m in history_messages for m in trimmed_messages
    )

    meta = SessionMeta(
        session_id=session_id,
        context_carried=context_carried,
        messages_sent=len(trimmed_messages),
        messages_trimmed=messages_trimmed,
        last_provider=last_provider,
        new_incoming_messages=new_incoming,
    )
    return trimmed_messages, meta


async def save_session_turn(
    session_factory: async_sessionmaker[AsyncSession],
    session_id: str,
    org_id: str,
    incoming_messages: list[Message] | list[dict[str, Any]] | None,
    assistant_content: str | None,
    provider: str,
    model: str,
) -> None:
    """Store the user/incoming input and assistant reply in session history and bump last_active_at."""
    now = datetime.now(UTC)
    try:
        async with session_factory() as session:
            record = await session.get(Session, session_id)
            if not record:
                return

            record.last_active_at = now

            incoming_list = incoming_messages or []
            for idx, msg in enumerate(incoming_list):
                role = msg.role if hasattr(msg, "role") else msg.get("role", "user")
                content = msg.content if hasattr(msg, "content") else msg.get("content", "")
                if content is None:
                    content = ""
                elif not isinstance(content, str):
                    content = str(content)
                msg_time = now + timedelta(microseconds=idx * 1000)
                user_msg = SessionMessage(
                    id=generate_id("msg"),
                    org_id=org_id,
                    session_id=session_id,
                    role=role,
                    content=content,
                    created_at=msg_time,
                )
                session.add(user_msg)

            if assistant_content is not None:
                assistant_time = now + timedelta(microseconds=(len(incoming_list) + 1) * 1000)
                assistant_msg = SessionMessage(
                    id=generate_id("msg"),
                    org_id=org_id,
                    session_id=session_id,
                    role="assistant",
                    content=str(assistant_content),
                    metadata_json={"provider": provider, "model": model},
                    created_at=assistant_time,
                )
                session.add(assistant_msg)

            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to save session turn for %s: %s", session_id, exc)


async def list_member_sessions(
    session: AsyncSession,
    org_id: str,
    user_id: str,
    is_admin: bool,
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[list[SessionItem], str | None]:
    """List sessions scoped to org and member's keys, with cursor pagination."""
    now = datetime.now(UTC)
    # 1. Purge expired sessions for this org
    expired_cutoff = now - EXPIRY_WINDOW
    await session.execute(
        delete(Session).where(Session.org_id == org_id, Session.last_active_at < expired_cutoff)
    )
    await session.commit()

    # 2. Get keys owned by this member (admins can view all org sessions)
    key_filter = None
    if not is_admin:
        key_res = await session.execute(
            select(PlatformKey.id).where(
                PlatformKey.org_id == org_id, PlatformKey.user_id == user_id
            )
        )
        user_key_ids = list(key_res.scalars().all())
        key_filter = Session.key_id.in_(user_key_ids)

    # 3. Build query with cursor pagination
    query = (
        select(Session, func.count(SessionMessage.id).label("message_count"))
        .outerjoin(SessionMessage, Session.id == SessionMessage.session_id)
        .where(Session.org_id == org_id)
        .group_by(Session.id)
        .order_by(Session.created_at.desc(), Session.id.desc())
    )

    if key_filter is not None:
        query = query.where(key_filter)

    if cursor:
        decoded = decode_cursor(cursor)
        if decoded:
            cursor_time, cursor_id = decoded
            query = query.where(
                (Session.created_at < cursor_time)
                | ((Session.created_at == cursor_time) & (Session.id < cursor_id))
            )

    query = query.limit(limit + 1)
    res = await session.execute(query)
    rows = res.all()

    items: list[SessionItem] = []
    has_more = len(rows) > limit
    target_rows = rows[:limit]

    for ses_row, count in target_rows:
        items.append(
            SessionItem(
                id=ses_row.id,
                org_id=ses_row.org_id,
                key_id=ses_row.key_id,
                created_at=ses_row.created_at,
                last_active_at=ses_row.last_active_at,
                message_count=count or 0,
            )
        )

    next_cursor = None
    if has_more and target_rows:
        last_item = target_rows[-1][0]
        next_cursor = encode_cursor(last_item.created_at, last_item.id)

    return items, next_cursor


async def get_member_session_detail(
    session: AsyncSession,
    session_id: str,
    org_id: str,
    user_id: str,
    is_admin: bool,
) -> SessionDetailResponse | None:
    """Retrieve full session detail and message history with 24h expiration on read."""
    now = datetime.now(UTC)
    record = await session.get(Session, session_id)
    if not record or record.org_id != org_id:
        return None

    # Check 24-hour expiration on read
    if now - record.last_active_at > EXPIRY_WINDOW:
        await session.delete(record)
        await session.commit()
        return None

    # Check user ownership if not admin
    if not is_admin:
        key_record = await session.get(PlatformKey, record.key_id)
        if not key_record or key_record.user_id != user_id:
            raise PermissionError("not authorized to read this session")

    # Fetch messages
    msg_stmt = (
        select(SessionMessage)
        .where(SessionMessage.session_id == session_id)
        .order_by(SessionMessage.created_at.asc())
    )
    res = await session.execute(msg_stmt)
    messages = list(res.scalars().all())

    return SessionDetailResponse(
        id=record.id,
        org_id=record.org_id,
        key_id=record.key_id,
        created_at=record.created_at,
        last_active_at=record.last_active_at,
        messages=[
            SessionMessageItem(
                id=m.id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
                metadata_json=m.metadata_json,
            )
            for m in messages
        ],
    )


async def delete_member_session(
    session: AsyncSession,
    session_id: str,
    org_id: str,
    user_id: str,
    is_admin: bool,
) -> bool:
    """Delete a session and cascade delete its messages."""
    record = await session.get(Session, session_id)
    if not record or record.org_id != org_id:
        return False

    if not is_admin:
        key_record = await session.get(PlatformKey, record.key_id)
        if not key_record or key_record.user_id != user_id:
            raise PermissionError("not authorized to delete this session")

    await session.delete(record)
    await session.commit()
    return True
