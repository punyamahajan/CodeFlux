from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import DateTime, Float, Integer, String, select
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class UsageRecord(Base):
    __tablename__ = "usage_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    team: Mapped[str] = mapped_column(String(100), index=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    key_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str] = mapped_column(String(200))
    request_count: Mapped[int] = mapped_column(Integer, default=1)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)


class Database:
    def __init__(self, url: str):
        self.engine = create_async_engine(url)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def initialize(self) -> None:
        if self.engine.url.get_backend_name() == "sqlite" and self.engine.url.database not in {None, ":memory:"}:
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
            existing = await session.scalar(select(Credential).where(Credential.reference == reference))
            if existing:
                existing.provider, existing.encrypted_value = provider, encrypted
            else:
                session.add(Credential(reference=reference, provider=provider, encrypted_value=encrypted))
            await session.commit()

    async def get(self, reference: str) -> str | None:
        async with self.sessions() as session:
            credential = await session.scalar(select(Credential).where(Credential.reference == reference))
            return self.fernet.decrypt(credential.encrypted_value.encode()).decode() if credential else None

    async def references(self, provider: str) -> list[str]:
        async with self.sessions() as session:
            values = await session.scalars(select(Credential.reference).where(Credential.provider == provider))
            return list(values)


class UsageRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def record(self, *, team: str, provider: str, key_ref: str | None, model: str, prompt_tokens: int, completion_tokens: int, estimated_cost: float = 0.0) -> None:
        async with self.sessions() as session:
            session.add(UsageRecord(team=team, provider=provider, key_ref=key_ref, model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, estimated_cost=estimated_cost))
            await session.commit()
