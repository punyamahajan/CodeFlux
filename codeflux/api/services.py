from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.api.schemas import decode_cursor, encode_cursor
from codeflux.db.models import (
    CreditLedger,
    LimitRequest,
    Organization,
    PlatformKey,
    ProviderCredential,
    RequestTrace,
    Route,
    User,
)
from codeflux.security.crypto import (
    encrypt_provider_key,
    generate_platform_key,
    hash_platform_key,
)
from codeflux.security.passwords import hash_password, verify_password
from codeflux.security.tokens import create_access_token

# ============================================================================
# Auth Service
# ============================================================================


class AuthService:
    @staticmethod
    async def admin_signup(
        session: AsyncSession,
        org_name: str,
        email: str,
        password: str,
        jwt_secret: str,
    ) -> tuple[User, Organization, str]:
        # Check if email is already registered in any org
        existing = await session.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "email_exists", "message": "Email is already registered"},
            )

        org = Organization(name=org_name)
        session.add(org)
        await session.flush()

        user = User(
            org_id=org.id,
            email=email,
            password_hash=hash_password(password),
            role="admin",
        )
        session.add(user)
        await session.flush()

        token = create_access_token(
            {"sub": user.id, "org_id": org.id, "role": user.role},
            secret=jwt_secret,
        )
        return user, org, token

    @staticmethod
    async def member_signup(
        session: AsyncSession,
        invite_code: str,
        email: str,
        password: str,
        jwt_secret: str,
    ) -> tuple[User, Organization, str]:
        # Find org by invite code (org id)
        org_res = await session.execute(select(Organization).where(Organization.id == invite_code))
        org = org_res.scalar_one_or_none()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "invalid_invite", "message": "Invalid or expired invite code"},
            )

        existing = await session.execute(
            select(User).where(User.org_id == org.id, User.email == email)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "email_exists", "message": "Email already in organization"},
            )

        user = User(
            org_id=org.id,
            email=email,
            password_hash=hash_password(password),
            role="member",
        )
        session.add(user)
        await session.flush()

        token = create_access_token(
            {"sub": user.id, "org_id": org.id, "role": user.role},
            secret=jwt_secret,
        )
        return user, org, token

    @staticmethod
    async def login(
        session: AsyncSession,
        email: str,
        password: str,
        jwt_secret: str,
        org_id: str | None = None,
    ) -> tuple[User, Organization, str]:
        stmt = select(User).where(User.email == email)
        if org_id:
            stmt = stmt.where(User.org_id == org_id)

        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "invalid_credentials", "message": "Invalid email or password"},
            )

        org_res = await session.execute(select(Organization).where(Organization.id == user.org_id))
        org = org_res.scalar_one()

        token = create_access_token(
            {"sub": user.id, "org_id": user.org_id, "role": user.role},
            secret=jwt_secret,
        )
        return user, org, token


# ============================================================================
# Vault Service
# ============================================================================


class VaultService:
    PROVIDER_TEST_CONFIGS: ClassVar[dict[str, dict[str, Any]]] = {
        "openai": {
            "url": "https://api.openai.com/v1/models",
            "header": "Authorization",
            "prefix": "Bearer ",
        },
        "gemini": {
            "url": "https://generativelanguage.googleapis.com/v1beta/models",
            "header": "x-goog-api-key",
            "prefix": "",
        },
        "groq": {
            "url": "https://api.groq.com/openai/v1/models",
            "header": "Authorization",
            "prefix": "Bearer ",
        },
        "openrouter": {
            "url": "https://openrouter.ai/api/v1/models",
            "header": "Authorization",
            "prefix": "Bearer ",
        },
        "mistral": {
            "url": "https://api.mistral.ai/v1/models",
            "header": "Authorization",
            "prefix": "Bearer ",
        },
        "ollama": {
            "url": "http://localhost:11434/api/tags",
            "header": "Authorization",
            "prefix": "Bearer ",
        },
    }

    @classmethod
    async def probe_provider_key(
        cls,
        client: httpx.AsyncClient,
        provider: str,
        api_key: str,
    ) -> bool:
        """Make one lightweight test call to verify the provider API key."""
        config = cls.PROVIDER_TEST_CONFIGS.get(provider.lower())
        url = config["url"] if config else f"https://api.{provider}.com/v1/models"
        header_name = config["header"] if config else "Authorization"
        prefix = config["prefix"] if config else "Bearer "

        headers = {header_name: f"{prefix}{api_key}"}
        try:
            resp = await client.get(url, headers=headers, timeout=10.0)
            return resp.status_code < 400
        except (httpx.HTTPError, TimeoutError):
            return False

    @classmethod
    async def add_credential(
        cls,
        session: AsyncSession,
        client: httpx.AsyncClient,
        org_id: str,
        provider: str,
        api_key: str,
        master_key: str,
    ) -> ProviderCredential:
        valid = await cls.probe_provider_key(client, provider, api_key)
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "invalid_provider_key",
                    "message": f"Provider test call failed for {provider}",
                },
            )

        key_hint = api_key[-4:] if len(api_key) >= 4 else api_key
        encrypted = encrypt_provider_key(api_key, master_key)

        credential = ProviderCredential(
            org_id=org_id,
            provider=provider.lower(),
            key_hint=key_hint,
            encrypted_key=encrypted,
            enabled=True,
        )
        session.add(credential)
        await session.flush()
        return credential

    @classmethod
    async def list_credentials(
        cls,
        session: AsyncSession,
        org_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[ProviderCredential], str | None]:
        stmt = select(ProviderCredential).where(ProviderCredential.org_id == org_id)

        if cursor:
            decoded = decode_cursor(cursor)
            if decoded:
                cursor_time, cursor_id = decoded
                stmt = stmt.where(
                    (ProviderCredential.created_at < cursor_time)
                    | (
                        (ProviderCredential.created_at == cursor_time)
                        & (ProviderCredential.id < cursor_id)
                    )
                )

        stmt = stmt.order_by(
            ProviderCredential.created_at.desc(), ProviderCredential.id.desc()
        ).limit(limit + 1)
        res = await session.execute(stmt)
        items = list(res.scalars().all())

        next_cursor = None
        if len(items) > limit:
            last = items[limit - 1]
            next_cursor = encode_cursor(last.created_at, last.id)
            items = items[:limit]

        return items, next_cursor

    @classmethod
    async def toggle_credential(
        cls,
        session: AsyncSession,
        org_id: str,
        cred_id: str,
        enabled: bool,
    ) -> ProviderCredential:
        stmt = select(ProviderCredential).where(
            ProviderCredential.id == cred_id, ProviderCredential.org_id == org_id
        )
        res = await session.execute(stmt)
        cred = res.scalar_one_or_none()
        if not cred:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "Provider credential not found"},
            )

        cred.enabled = enabled
        await session.flush()
        return cred

    @classmethod
    async def delete_credential(
        cls,
        session: AsyncSession,
        org_id: str,
        cred_id: str,
    ) -> None:
        stmt = select(ProviderCredential).where(
            ProviderCredential.id == cred_id, ProviderCredential.org_id == org_id
        )
        res = await session.execute(stmt)
        cred = res.scalar_one_or_none()
        if not cred:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "Provider credential not found"},
            )
        await session.delete(cred)
        await session.flush()


# ============================================================================
# Platform Keys Service
# ============================================================================


class PlatformKeyService:
    @classmethod
    async def create_key(
        cls,
        session: AsyncSession,
        org_id: str,
        user_id: str,
        name: str,
        credit_limit_micro: int,
        rpm_limit: int,
        allowed_routes: list[str],
        expires_at: datetime | None,
        hmac_secret: str,
    ) -> tuple[PlatformKey, str]:
        # Verify user belongs to same org
        user_res = await session.execute(
            select(User).where(User.id == user_id, User.org_id == org_id)
        )
        if not user_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "User not found in organization"},
            )

        plaintext_key = generate_platform_key()
        prefix = plaintext_key[:16]
        digest = hash_platform_key(plaintext_key, hmac_secret)

        key = PlatformKey(
            org_id=org_id,
            user_id=user_id,
            name=name,
            key_prefix=prefix,
            key_digest=digest,
            credit_limit_micro=credit_limit_micro,
            credit_remaining_micro=credit_limit_micro,
            rpm_limit=rpm_limit,
            allowed_routes=allowed_routes,
            expires_at=expires_at,
        )
        session.add(key)
        await session.flush()

        # Initial credit ledger entry if credits > 0
        if credit_limit_micro > 0:
            ledger = CreditLedger(
                org_id=org_id,
                key_id=key.id,
                amount_micro=credit_limit_micro,
                balance_after_micro=credit_limit_micro,
                reason="initial_grant",
            )
            session.add(ledger)
            await session.flush()

        return key, plaintext_key

    @classmethod
    async def list_keys(
        cls,
        session: AsyncSession,
        org_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[PlatformKey], str | None]:
        stmt = select(PlatformKey).where(PlatformKey.org_id == org_id)

        if cursor:
            decoded = decode_cursor(cursor)
            if decoded:
                cursor_time, cursor_id = decoded
                stmt = stmt.where(
                    (PlatformKey.created_at < cursor_time)
                    | ((PlatformKey.created_at == cursor_time) & (PlatformKey.id < cursor_id))
                )

        stmt = stmt.order_by(PlatformKey.created_at.desc(), PlatformKey.id.desc()).limit(limit + 1)
        res = await session.execute(stmt)
        items = list(res.scalars().all())

        next_cursor = None
        if len(items) > limit:
            last = items[limit - 1]
            next_cursor = encode_cursor(last.created_at, last.id)
            items = items[:limit]

        return items, next_cursor

    @classmethod
    async def get_key(
        cls,
        session: AsyncSession,
        org_id: str,
        key_id: str,
    ) -> PlatformKey:
        stmt = select(PlatformKey).where(PlatformKey.id == key_id, PlatformKey.org_id == org_id)
        res = await session.execute(stmt)
        key = res.scalar_one_or_none()
        if not key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "Platform key not found"},
            )
        return key

    @classmethod
    async def patch_key(
        cls,
        session: AsyncSession,
        org_id: str,
        key_id: str,
        name: str | None = None,
        credit_limit_micro: int | None = None,
        rpm_limit: int | None = None,
        allowed_routes: list[str] | None = None,
        expires_at: datetime | None = None,
    ) -> PlatformKey:
        key = await cls.get_key(session, org_id, key_id)

        if name is not None:
            key.name = name
        if rpm_limit is not None:
            key.rpm_limit = rpm_limit
        if allowed_routes is not None:
            key.allowed_routes = allowed_routes
        if expires_at is not None:
            key.expires_at = expires_at

        if credit_limit_micro is not None and credit_limit_micro != key.credit_limit_micro:
            delta = credit_limit_micro - key.credit_limit_micro
            key.credit_limit_micro = credit_limit_micro
            key.credit_remaining_micro += delta

            ledger = CreditLedger(
                org_id=org_id,
                key_id=key.id,
                amount_micro=delta,
                balance_after_micro=key.credit_remaining_micro,
                reason="admin_adjustment",
            )
            session.add(ledger)

        await session.flush()
        return key

    @classmethod
    async def revoke_key(
        cls,
        session: AsyncSession,
        org_id: str,
        key_id: str,
    ) -> PlatformKey:
        key = await cls.get_key(session, org_id, key_id)
        key.revoked_at = datetime.now(UTC)
        await session.flush()
        return key


# ============================================================================
# Route Service
# ============================================================================


class RouteService:
    @classmethod
    async def create_route(
        cls,
        session: AsyncSession,
        org_id: str,
        alias: str,
        strategy: str,
        task_tag: str | None,
        candidates: list[dict[str, Any]],
    ) -> Route:
        existing = await session.execute(
            select(Route).where(Route.org_id == org_id, Route.alias == alias)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "alias_conflict", "message": f"Route '{alias}' already exists"},
            )

        route = Route(
            org_id=org_id,
            alias=alias,
            strategy=strategy,
            task_tag=task_tag,
            candidates=candidates,
        )
        session.add(route)
        await session.flush()
        return route

    @classmethod
    async def list_routes(
        cls,
        session: AsyncSession,
        org_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[Route], str | None]:
        stmt = select(Route).where(Route.org_id == org_id)

        if cursor:
            decoded = decode_cursor(cursor)
            if decoded:
                cursor_time, cursor_id = decoded
                stmt = stmt.where(
                    (Route.created_at < cursor_time)
                    | ((Route.created_at == cursor_time) & (Route.id < cursor_id))
                )

        stmt = stmt.order_by(Route.created_at.desc(), Route.id.desc()).limit(limit + 1)
        res = await session.execute(stmt)
        items = list(res.scalars().all())

        next_cursor = None
        if len(items) > limit:
            last = items[limit - 1]
            next_cursor = encode_cursor(last.created_at, last.id)
            items = items[:limit]

        return items, next_cursor

    @classmethod
    async def get_route(
        cls,
        session: AsyncSession,
        org_id: str,
        route_id: str,
    ) -> Route:
        stmt = select(Route).where(Route.id == route_id, Route.org_id == org_id)
        res = await session.execute(stmt)
        route = res.scalar_one_or_none()
        if not route:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "Route not found"},
            )
        return route

    @classmethod
    async def update_route(
        cls,
        session: AsyncSession,
        org_id: str,
        route_id: str,
        alias: str | None = None,
        strategy: str | None = None,
        task_tag: str | None = None,
        candidates: list[dict[str, Any]] | None = None,
    ) -> Route:
        route = await cls.get_route(session, org_id, route_id)

        if alias is not None and alias != route.alias:
            existing = await session.execute(
                select(Route).where(Route.org_id == org_id, Route.alias == alias)
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "alias_conflict", "message": f"Route '{alias}' already exists"},
                )
            route.alias = alias

        if strategy is not None:
            route.strategy = strategy
        if task_tag is not None:
            route.task_tag = task_tag
        if candidates is not None:
            route.candidates = candidates

        route.updated_at = datetime.now(UTC)
        await session.flush()
        return route

    @classmethod
    async def delete_route(
        cls,
        session: AsyncSession,
        org_id: str,
        route_id: str,
    ) -> None:
        route = await cls.get_route(session, org_id, route_id)
        await session.delete(route)
        await session.flush()


# ============================================================================
# Limit Request Service
# ============================================================================


class LimitRequestService:
    @classmethod
    async def create_request(
        cls,
        session: AsyncSession,
        org_id: str,
        user_id: str,
        key_id: str,
        requested_credit_micro: int,
        reason: str | None,
    ) -> LimitRequest:
        # Key must exist, belong to org, and belong to user
        stmt = select(PlatformKey).where(
            PlatformKey.id == key_id,
            PlatformKey.org_id == org_id,
            PlatformKey.user_id == user_id,
        )
        res = await session.execute(stmt)
        key = res.scalar_one_or_none()
        if not key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "Key not found for this user"},
            )

        req = LimitRequest(
            org_id=org_id,
            user_id=user_id,
            key_id=key_id,
            requested_credit_micro=requested_credit_micro,
            reason=reason,
            status="pending",
        )
        session.add(req)
        await session.flush()
        return req

    @classmethod
    async def list_member_requests(
        cls,
        session: AsyncSession,
        org_id: str,
        user_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[LimitRequest], str | None]:
        stmt = select(LimitRequest).where(
            LimitRequest.org_id == org_id, LimitRequest.user_id == user_id
        )

        if cursor:
            decoded = decode_cursor(cursor)
            if decoded:
                cursor_time, cursor_id = decoded
                stmt = stmt.where(
                    (LimitRequest.created_at < cursor_time)
                    | ((LimitRequest.created_at == cursor_time) & (LimitRequest.id < cursor_id))
                )

        stmt = stmt.order_by(LimitRequest.created_at.desc(), LimitRequest.id.desc()).limit(
            limit + 1
        )
        res = await session.execute(stmt)
        items = list(res.scalars().all())

        next_cursor = None
        if len(items) > limit:
            last = items[limit - 1]
            next_cursor = encode_cursor(last.created_at, last.id)
            items = items[:limit]

        return items, next_cursor

    @classmethod
    async def list_admin_requests(
        cls,
        session: AsyncSession,
        org_id: str,
        status_filter: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[LimitRequest], str | None]:
        stmt = select(LimitRequest).where(LimitRequest.org_id == org_id)
        if status_filter:
            stmt = stmt.where(LimitRequest.status == status_filter)

        if cursor:
            decoded = decode_cursor(cursor)
            if decoded:
                cursor_time, cursor_id = decoded
                stmt = stmt.where(
                    (LimitRequest.created_at < cursor_time)
                    | ((LimitRequest.created_at == cursor_time) & (LimitRequest.id < cursor_id))
                )

        stmt = stmt.order_by(LimitRequest.created_at.desc(), LimitRequest.id.desc()).limit(
            limit + 1
        )
        res = await session.execute(stmt)
        items = list(res.scalars().all())

        next_cursor = None
        if len(items) > limit:
            last = items[limit - 1]
            next_cursor = encode_cursor(last.created_at, last.id)
            items = items[:limit]

        return items, next_cursor

    @classmethod
    async def approve_request(
        cls,
        session: AsyncSession,
        org_id: str,
        reviewer_id: str,
        request_id: str,
        approved_credit_micro: int | None = None,
    ) -> tuple[LimitRequest, CreditLedger]:
        stmt = select(LimitRequest).where(
            LimitRequest.id == request_id, LimitRequest.org_id == org_id
        )
        res = await session.execute(stmt)
        req = res.scalar_one_or_none()
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "Limit request not found"},
            )

        if req.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_status", "message": f"Request is already {req.status}"},
            )

        # Get key
        key_res = await session.execute(
            select(PlatformKey).where(PlatformKey.id == req.key_id, PlatformKey.org_id == org_id)
        )
        key = key_res.scalar_one_or_none()
        if not key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "Associated platform key not found"},
            )

        new_limit = (
            approved_credit_micro
            if approved_credit_micro is not None
            else req.requested_credit_micro
        )
        delta = new_limit - key.credit_limit_micro

        req.status = "approved"
        req.reviewed_by = reviewer_id
        req.reviewed_at = datetime.now(UTC)

        key.credit_limit_micro = new_limit
        key.credit_remaining_micro += delta

        ledger = CreditLedger(
            org_id=org_id,
            key_id=key.id,
            amount_micro=delta,
            balance_after_micro=key.credit_remaining_micro,
            reason=f"limit_request_approved:{req.id}",
        )
        session.add(ledger)
        await session.flush()

        return req, ledger

    @classmethod
    async def deny_request(
        cls,
        session: AsyncSession,
        org_id: str,
        reviewer_id: str,
        request_id: str,
    ) -> LimitRequest:
        stmt = select(LimitRequest).where(
            LimitRequest.id == request_id, LimitRequest.org_id == org_id
        )
        res = await session.execute(stmt)
        req = res.scalar_one_or_none()
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "Limit request not found"},
            )

        if req.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_status", "message": f"Request is already {req.status}"},
            )

        req.status = "denied"
        req.reviewed_by = reviewer_id
        req.reviewed_at = datetime.now(UTC)
        await session.flush()
        return req


# ============================================================================
# Usage Service
# ============================================================================


class UsageService:
    @classmethod
    async def get_usage_overview(
        cls,
        session: AsyncSession,
        org_id: str,
        user_id: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate totals by key and model, calculate cost per 1K tokens, and list ledger entries.

        If user_id is provided, filters to keys owned by that member.
        """
        # 1. Fetch keys (all in org for admin, member's own for member)
        key_stmt = select(PlatformKey).where(PlatformKey.org_id == org_id)
        if user_id:
            key_stmt = key_stmt.where(PlatformKey.user_id == user_id)
        key_res = await session.execute(key_stmt)
        keys = list(key_res.scalars().all())
        key_ids = [k.id for k in keys]

        if not key_ids:
            return {
                "total_requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "total_cost_micro": 0,
                "total_credits_remaining_micro": 0,
                "cost_per_1k_tokens_micro": 0,
                "by_key": [],
                "by_model": [],
                "ledger": [],
                "next_cursor": None,
            }

        # 2. Fetch traces for these keys
        trace_stmt = select(RequestTrace).where(
            RequestTrace.org_id == org_id, RequestTrace.key_id.in_(key_ids)
        )
        trace_res = await session.execute(trace_stmt)
        traces = list(trace_res.scalars().all())

        # 3. Aggregate totals by key
        key_traces: dict[str, list[RequestTrace]] = {k.id: [] for k in keys}
        for trace in traces:
            if trace.key_id in key_traces:
                key_traces[trace.key_id].append(trace)

        by_key = []
        for k in keys:
            kts = key_traces[k.id]
            req_cnt = len(kts)
            p_tok = sum(t.prompt_tokens for t in kts)
            c_tok = sum(t.completion_tokens for t in kts)
            tot_tok = p_tok + c_tok
            cost_micro = sum(t.cost_micro for t in kts)
            cost_per_1k = (cost_micro * 1000) // tot_tok if tot_tok > 0 else 0
            by_key.append(
                {
                    "key_id": k.id,
                    "key_name": k.name,
                    "key_prefix": k.key_prefix,
                    "credit_limit_micro": k.credit_limit_micro,
                    "credit_remaining_micro": k.credit_remaining_micro,
                    "total_requests": req_cnt,
                    "prompt_tokens": p_tok,
                    "completion_tokens": c_tok,
                    "total_tokens": tot_tok,
                    "total_cost_micro": cost_micro,
                    "cost_per_1k_tokens_micro": cost_per_1k,
                }
            )

        # 4. Aggregate totals by model
        model_traces: dict[str, list[RequestTrace]] = {}
        for trace in traces:
            m = trace.model or "unknown"
            model_traces.setdefault(m, []).append(trace)

        by_model = []
        for model_name, mts in sorted(model_traces.items()):
            req_cnt = len(mts)
            p_tok = sum(t.prompt_tokens for t in mts)
            c_tok = sum(t.completion_tokens for t in mts)
            tot_tok = p_tok + c_tok
            cost_micro = sum(t.cost_micro for t in mts)
            cost_per_1k = (cost_micro * 1000) // tot_tok if tot_tok > 0 else 0
            by_model.append(
                {
                    "model": model_name,
                    "total_requests": req_cnt,
                    "prompt_tokens": p_tok,
                    "completion_tokens": c_tok,
                    "total_tokens": tot_tok,
                    "total_cost_micro": cost_micro,
                    "cost_per_1k_tokens_micro": cost_per_1k,
                }
            )

        # 5. Overall summary
        total_requests = len(traces)
        total_prompt_tokens = sum(t.prompt_tokens for t in traces)
        total_completion_tokens = sum(t.completion_tokens for t in traces)
        total_tokens = total_prompt_tokens + total_completion_tokens
        total_cost_micro = sum(t.cost_micro for t in traces)
        total_credits_remaining_micro = sum(k.credit_remaining_micro for k in keys)
        cost_per_1k_tokens_micro = (
            (total_cost_micro * 1000) // total_tokens if total_tokens > 0 else 0
        )

        # 6. Fetch ledger rows with cursor pagination
        ledger_stmt = select(CreditLedger).where(
            CreditLedger.org_id == org_id, CreditLedger.key_id.in_(key_ids)
        )
        if cursor:
            decoded = decode_cursor(cursor)
            if decoded:
                cursor_time, cursor_id = decoded
                ledger_stmt = ledger_stmt.where(
                    (CreditLedger.created_at < cursor_time)
                    | ((CreditLedger.created_at == cursor_time) & (CreditLedger.id < cursor_id))
                )

        ledger_stmt = ledger_stmt.order_by(
            CreditLedger.created_at.desc(), CreditLedger.id.desc()
        ).limit(limit + 1)
        ledger_res = await session.execute(ledger_stmt)
        ledger_items = list(ledger_res.scalars().all())

        next_cursor = None
        if len(ledger_items) > limit:
            last = ledger_items[limit - 1]
            next_cursor = encode_cursor(last.created_at, last.id)
            ledger_items = ledger_items[:limit]

        return {
            "total_requests": total_requests,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "total_cost_micro": total_cost_micro,
            "total_credits_remaining_micro": total_credits_remaining_micro,
            "cost_per_1k_tokens_micro": cost_per_1k_tokens_micro,
            "by_key": by_key,
            "by_model": by_model,
            "ledger": ledger_items,
            "next_cursor": next_cursor,
        }
