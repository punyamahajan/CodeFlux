from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Credential(Base):
    __tablename__ = "credentials"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    encrypted_value: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class UsageRecord(Base):
    __tablename__ = "usage_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    team: Mapped[str] = mapped_column(String(100), index=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    key_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str] = mapped_column(String(200))
    request_count: Mapped[int] = mapped_column(Integer, default=1)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)


class ClientApiKey(Base):
    __tablename__ = "client_api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    team: Mapped[str] = mapped_column(String(100), index=True)
    key_prefix: Mapped[str] = mapped_column(String(20), index=True)
    key_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    monthly_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Database:
    def __init__(self, url: str):
        self.engine = create_async_engine(url)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def initialize(self) -> None:
        if self.engine.url.get_backend_name() == "sqlite" and self.engine.url.database not in {
            None,
            ":memory:",
        }:
            Path(self.engine.url.database).parent.mkdir(parents=True, exist_ok=True)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()


class CredentialVault:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], master_secret: str):
        digest = hashlib.sha256(master_secret.encode()).digest()
        self.fernet = Fernet(base64.urlsafe_b64encode(digest))
        self.sessions = sessions

    async def put(self, reference: str, provider: str, value: str) -> None:
        encrypted = self.fernet.encrypt(value.encode()).decode()
        async with self.sessions() as session:
            existing = await session.scalar(
                select(Credential).where(Credential.reference == reference)
            )
            if existing:
                existing.provider, existing.encrypted_value = provider, encrypted
            else:
                session.add(
                    Credential(reference=reference, provider=provider, encrypted_value=encrypted)
                )
            await session.commit()

    async def get(self, reference: str) -> str | None:
        async with self.sessions() as session:
            credential = await session.scalar(
                select(Credential).where(Credential.reference == reference)
            )
            if not credential:
                return None
            try:
                return self.fernet.decrypt(credential.encrypted_value.encode()).decode()
            except InvalidToken:
                return None

    async def references(self, provider: str) -> list[str]:
        async with self.sessions() as session:
            values = await session.scalars(
                select(Credential.reference).where(Credential.provider == provider)
            )
            return list(values)

    def _decrypts(self, encrypted_value: str) -> bool:
        try:
            self.fernet.decrypt(encrypted_value.encode())
            return True
        except InvalidToken:
            return False

    async def list_metadata(self) -> list[dict[str, object]]:
        async with self.sessions() as session:
            values = await session.scalars(
                select(Credential).order_by(Credential.provider, Credential.reference)
            )
            return [
                {
                    "reference": item.reference,
                    "provider": item.provider,
                    "created_at": item.created_at.isoformat(),
                    "usable": self._decrypts(item.encrypted_value),
                }
                for item in values
            ]


class UsageRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def record(
        self,
        *,
        team: str,
        provider: str,
        key_ref: str | None,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost: float = 0.0,
    ) -> None:
        async with self.sessions() as session:
            session.add(
                UsageRecord(
                    team=team,
                    provider=provider,
                    key_ref=key_ref,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    estimated_cost=estimated_cost,
                )
            )
            await session.commit()

    async def summary(self, team: str | None = None) -> dict[str, object]:
        async with self.sessions() as session:
            filters = [] if team is None else [UsageRecord.team == team]
            now = datetime.now(UTC)
            month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
            totals = (
                await session.execute(
                    select(
                        func.count(UsageRecord.id),
                        func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
                        func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
                    ).where(*filters)
                )
            ).one()
            latest = await session.scalar(
                select(UsageRecord).where(*filters).order_by(UsageRecord.timestamp.desc()).limit(1)
            )
            by_team_rows = await session.execute(
                select(
                    UsageRecord.team,
                    func.count(UsageRecord.id),
                    func.coalesce(
                        func.sum(UsageRecord.prompt_tokens + UsageRecord.completion_tokens), 0
                    ),
                )
                .where(*filters)
                .group_by(UsageRecord.team)
                .order_by(UsageRecord.team)
            )
            monthly_rows = await session.execute(
                select(
                    UsageRecord.team,
                    func.coalesce(
                        func.sum(UsageRecord.prompt_tokens + UsageRecord.completion_tokens), 0
                    ),
                )
                .where(*filters, UsageRecord.timestamp >= month_start)
                .group_by(UsageRecord.team)
            )
            monthly_by_team = {row[0]: int(row[1]) for row in monthly_rows}
            return {
                "requests": totals[0],
                "prompt_tokens": totals[1],
                "completion_tokens": totals[2],
                "total_tokens": totals[1] + totals[2],
                "by_team": [
                    {
                        "team": row[0],
                        "requests": row[1],
                        "total_tokens": row[2],
                        "tokens_this_month": monthly_by_team.get(row[0], 0),
                    }
                    for row in by_team_rows
                ],
                "latest": None
                if latest is None
                else {
                    "provider": latest.provider,
                    "model": latest.model,
                    "key_ref": latest.key_ref,
                    "team": latest.team,
                    "timestamp": latest.timestamp.isoformat(),
                },
            }

    async def tokens_this_month(self, team: str) -> int:
        now = datetime.now(UTC)
        month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
        async with self.sessions() as session:
            value = await session.scalar(
                select(
                    func.coalesce(
                        func.sum(UsageRecord.prompt_tokens + UsageRecord.completion_tokens), 0
                    )
                ).where(UsageRecord.team == team, UsageRecord.timestamp >= month_start)
            )
            return int(value or 0)


class ClientKeyRepository:
    """Persistent CodeFlux client keys. Only an HMAC digest is stored."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], master_secret: str):
        self.sessions = sessions
        self.secret = master_secret.encode()

    def _digest(self, value: str) -> str:
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    async def create(self, name: str, team: str, monthly_token_limit: int | None = None) -> str:
        raw = f"cf_{secrets.token_urlsafe(32)}"
        async with self.sessions() as session:
            session.add(
                ClientApiKey(
                    name=name,
                    team=team,
                    key_prefix=raw[:11],
                    key_digest=self._digest(raw),
                    monthly_token_limit=monthly_token_limit,
                )
            )
            await session.commit()
        return raw

    async def authenticate(self, value: str) -> dict[str, object] | None:
        digest = self._digest(value)
        async with self.sessions() as session:
            item = await session.scalar(
                select(ClientApiKey).where(
                    ClientApiKey.key_digest == digest, ClientApiKey.active.is_(True)
                )
            )
            if item is None:
                return None
            item.last_used_at = datetime.now(UTC)
            await session.commit()
            return {
                "id": item.id,
                "name": item.name,
                "team": item.team,
                "monthly_token_limit": item.monthly_token_limit,
            }

    async def list(self) -> list[dict[str, object]]:
        async with self.sessions() as session:
            values = await session.scalars(
                select(ClientApiKey).order_by(ClientApiKey.created_at.desc())
            )
            return [
                {
                    "id": item.id,
                    "name": item.name,
                    "team": item.team,
                    "key_prefix": f"{item.key_prefix}…",
                    "monthly_token_limit": item.monthly_token_limit,
                    "active": item.active,
                    "created_at": item.created_at.isoformat(),
                    "last_used_at": item.last_used_at.isoformat() if item.last_used_at else None,
                }
                for item in values
            ]

    async def revoke(self, key_id: int) -> None:
        async with self.sessions() as session:
            item = await session.get(ClientApiKey, key_id)
            if item:
                item.active = False
                await session.commit()
