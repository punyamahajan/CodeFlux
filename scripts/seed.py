"""Idempotent seed script for OmniKey demo workspace and synthetic data."""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from codeflux.db.models import (
    CreditLedger,
    Organization,
    PlatformKey,
    ProviderCredential,
    RequestTrace,
    Route,
    User,
)
from codeflux.db.session import Database
from codeflux.metering.pricing import compute_cost
from codeflux.schemas import Usage
from codeflux.security.crypto import encrypt_provider_key, hash_platform_key
from codeflux.security.passwords import hash_password
from codeflux.settings import Settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed")

DEMO_ORG_ID = "org_demo_omnikey0001"
ADMIN_EMAIL = "admin@omnikey.demo"
ALICE_EMAIL = "alice@omnikey.demo"
BOB_EMAIL = "bob@omnikey.demo"

ADMIN_RAW_KEY = "ok_live_demo_admin_secret_key_12345"
ALICE_RAW_KEY = "ok_live_demo_alice_secret_key_12345"
BOB_RAW_KEY = "ok_live_demo_bob_secret_key_12345"


async def seed() -> None:
    settings = Settings()
    db = Database(settings.database_url)

    async with db.sessions() as session:
        # 1. Organization
        org = await session.get(Organization, DEMO_ORG_ID)
        if not org:
            org = Organization(id=DEMO_ORG_ID, name="OmniKey Demo Org")
            session.add(org)
            await session.flush()
            logger.info("Created Demo Org: %s", org.id)
        else:
            logger.info("Demo Org already exists: %s", org.id)

        # 2. Users (Admin + 2 Members)
        pw_hash = hash_password("demopassword123")

        async def get_or_create_user(email: str, role: str) -> User:
            stmt = select(User).where(User.org_id == org.id, User.email == email)
            res = await session.execute(stmt)
            u = res.scalar_one_or_none()
            if not u:
                u = User(org_id=org.id, email=email, password_hash=pw_hash, role=role)
                session.add(u)
                await session.flush()
                logger.info("Created User %s (%s)", email, role)
            return u

        admin_user = await get_or_create_user(ADMIN_EMAIL, "admin")
        alice_user = await get_or_create_user(ALICE_EMAIL, "member")
        bob_user = await get_or_create_user(BOB_EMAIL, "member")

        # 3. Provider Credentials
        import os

        from dotenv import load_dotenv

        load_dotenv()

        live_openai = os.getenv("OPENAI_API_KEY") or "sk-proj-demo-openai-key-abcde1234"
        live_gemini = os.getenv("GEMINI_API_KEY") or "AQ.Ab8-demo-gemini-key-xyz9876"
        live_groq = os.getenv("GROQ_API_KEY") or "gsk_demo_groq_key_long_string_5555"
        live_ollama = os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434/v1"

        providers = [
            ("openai", live_openai, live_openai[-4:] if len(live_openai) >= 4 else "1234"),
            ("gemini", live_gemini, live_gemini[-4:] if len(live_gemini) >= 4 else "9876"),
            ("groq", live_groq, live_groq[-4:] if len(live_groq) >= 4 else "5555"),
            ("ollama", live_ollama, "locl"),
        ]
        for prov, raw_k, hint in providers:
            stmt = select(ProviderCredential).where(
                ProviderCredential.org_id == org.id, ProviderCredential.provider == prov
            )
            res = await session.execute(stmt)
            existing_cred = res.scalar_one_or_none()
            if not existing_cred:
                c = ProviderCredential(
                    org_id=org.id,
                    provider=prov,
                    key_hint=hint,
                    encrypted_key=encrypt_provider_key(raw_k, settings.master_key),
                    enabled=True,
                )
                session.add(c)
                logger.info("Added provider credential: %s", prov)
            else:
                existing_cred.encrypted_key = encrypt_provider_key(raw_k, settings.master_key)
                existing_cred.key_hint = hint
                logger.info("Updated provider credential with live key: %s", prov)

        # 4. Routes (fast, smart, code)
        route_configs = [
            (
                "fast",
                "least-latency",
                [
                    {"provider": "groq", "model": "qwen/qwen3.8-27b", "timeout_seconds": 15},
                    {"provider": "gemini", "model": "gemini-2.5-flash-lite", "timeout_seconds": 15},
                    {"provider": "openai", "model": "gpt-4o-mini", "timeout_seconds": 15},
                ],
            ),
            (
                "smart",
                "priority",
                [
                    {"provider": "gemini", "model": "gemini-2.5-flash-lite", "timeout_seconds": 15},
                    {"provider": "groq", "model": "qwen/qwen3.8-27b", "timeout_seconds": 15},
                    {"provider": "openai", "model": "gpt-4o-mini", "timeout_seconds": 15},
                ],
            ),
            (
                "code",
                "priority",
                [
                    {"provider": "groq", "model": "qwen/qwen3.8-27b", "timeout_seconds": 15},
                    {"provider": "gemini", "model": "gemini-2.5-flash-lite", "timeout_seconds": 15},
                    {"provider": "ollama", "model": "qwen2.5-coder", "timeout_seconds": 30},
                ],
            ),
        ]
        for alias, strat, cands in route_configs:
            stmt = select(Route).where(Route.org_id == org.id, Route.alias == alias)
            res = await session.execute(stmt)
            existing_route = res.scalar_one_or_none()
            if not existing_route:
                r = Route(
                    org_id=org.id,
                    alias=alias,
                    strategy=strat,
                    candidates=cands,
                )
                session.add(r)
                logger.info("Added route: %s", alias)
            else:
                existing_route.candidates = cands
                existing_route.strategy = strat
                logger.info("Updated route candidates: %s", alias)

        # 5. Platform Keys
        keys_setup = [
            (admin_user.id, "Admin Production Key", ADMIN_RAW_KEY, 100_000_000),  # $100
            (alice_user.id, "Alice Dev Key", ALICE_RAW_KEY, 25_000_000),  # $25
            (bob_user.id, "Bob Script Key", BOB_RAW_KEY, 15_000_000),  # $15
        ]
        platform_keys: list[PlatformKey] = []
        for uid, kname, raw_k, limit_m in keys_setup:
            digest = hash_platform_key(raw_k, settings.key_hmac_secret)
            stmt = select(PlatformKey).where(PlatformKey.key_digest == digest)
            res = await session.execute(stmt)
            pk = res.scalar_one_or_none()
            if not pk:
                pk = PlatformKey(
                    org_id=org.id,
                    user_id=uid,
                    name=kname,
                    key_prefix=raw_k[:16],
                    key_digest=digest,
                    credit_limit_micro=limit_m,
                    credit_remaining_micro=limit_m,
                    rpm_limit=60,
                )
                session.add(pk)
                await session.flush()
                logger.info("Created platform key: %s (%s)", kname, pk.id)
            platform_keys.append(pk)

        # 6. Check existing demo traces for idempotence
        stmt_count = select(func.count(RequestTrace.id)).where(RequestTrace.org_id == org.id)
        res_count = await session.execute(stmt_count)
        trace_count = res_count.scalar() or 0

        if trace_count >= 180:
            logger.info(
                "Demo traces already seeded (%d existing). Skipping trace duplication.", trace_count
            )
            await session.commit()
            await db.close()
            return

        # 7. Generate ~200 synthetic traces across 7 days
        logger.info("Generating 200 synthetic traces across 7 days...")
        now = datetime.now(UTC)
        available_models = [
            ("openai", "gpt-4o-mini"),
            ("gemini", "gemini-2.0-flash"),
            ("groq", "llama-3.3-70b-versatile"),
            ("groq", "qwen/qwen3.8-27b"),
        ]

        # Track ledger amounts per key to keep ledger invariant strictly valid
        key_balances = {k.id: k.credit_remaining_micro for k in platform_keys}

        random.seed(42)  # Deterministic seed data
        for i in range(200):
            # Spread over last 7 days
            days_ago = random.uniform(0.1, 6.9)
            trace_time = now - timedelta(days=days_ago)

            prov, mod = random.choice(available_models)
            pt = random.randint(15, 650)
            ct = random.randint(25, 450)
            usage_obj = Usage(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct)
            cost_res = compute_cost(usage_obj, mod)
            lat = random.randint(110, 850)
            status = 200 if random.random() > 0.05 else 429

            tid = f"trc_demo_{uuid.uuid4().hex[:20]}"
            target_key = random.choice(platform_keys)

            facts = {
                "schema_version": 1,
                "is_demo": True,
                "provider": prov,
                "model": mod,
                "status_code": status,
                "latency_ms": lat,
                "prompt_tokens": pt,
                "completion_tokens": ct,
                "total_tokens": pt + ct,
                "pricing_version": cost_res.price_version,
                "charged_cost_micro": cost_res.charged_micro if status == 200 else 0,
                "list_cost_micro": cost_res.list_micro if status == 200 else 0,
                "savings_micro": cost_res.savings_micro if status == 200 else 0,
                "is_estimate": True,
                "attempts": [
                    {
                        "provider": prov,
                        "model": mod,
                        "status_code": status,
                        "latency_ms": lat,
                        "error": None if status == 200 else "Rate limit reached",
                        "skipped": False,
                    }
                ],
            }

            cost_charged = cost_res.charged_micro if status == 200 else 0
            t = RequestTrace(
                id=tid,
                org_id=org.id,
                key_id=target_key.id,
                provider=prov,
                model=mod,
                status_code=status,
                latency_ms=lat,
                prompt_tokens=pt,
                completion_tokens=ct,
                cost_micro=cost_charged,
                facts=facts,
                created_at=trace_time,
            )
            session.add(t)

            # Record corresponding ledger entry and decrement balance
            if cost_charged > 0:
                key_balances[target_key.id] -= cost_charged
                entry = CreditLedger(
                    org_id=org.id,
                    key_id=target_key.id,
                    amount_micro=-cost_charged,
                    balance_after_micro=key_balances[target_key.id],
                    reason="usage_deduction",
                    trace_id=tid,
                    created_at=trace_time,
                )
                session.add(entry)

        # Update final balances on platform keys so the ledger invariant holds
        for pk in platform_keys:
            pk.credit_remaining_micro = key_balances[pk.id]
            logger.info(
                "Platform key %s remaining: %d (limit %d)",
                pk.name,
                pk.credit_remaining_micro,
                pk.credit_limit_micro,
            )

        await session.commit()
        logger.info("Successfully completed seed script.")

    await db.close()


if __name__ == "__main__":
    asyncio.run(seed())
