from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

from codeflux.api import (
    admin_requests_router,
    admin_traces_router,
    admin_usage_router,
    arena_router,
    auth_router,
    demo_router,
    explain_router,
    keys_router,
    member_requests_router,
    member_sessions_router,
    member_usage_router,
    playground_router,
    routes_router,
    vault_router,
)
from codeflux.db.session import get_shared_database
from codeflux.errors import NoProviderAvailable, ProviderError
from codeflux.gateway.auth import authenticate
from codeflux.gateway.circuit import CircuitBreaker
from codeflux.gateway.keypool import KeyPool
from codeflux.gateway.normalization import (
    gemini_chunk,
    gemini_request,
    openai_request,
    to_gemini,
    to_openai,
)
from codeflux.gateway.pii import PIIRedactor
from codeflux.gateway.ratelimit import SlidingWindowRpmLimiter
from codeflux.gateway.router import RoutingEngine
from codeflux.logging import configure_logging
from codeflux.metering.service import record_usage_and_trace
from codeflux.providers.registry import AdapterRegistry
from codeflux.schemas import GeminiRequest
from codeflux.sessions.service import (
    get_or_create_gateway_session,
    prepare_session_messages,
    save_session_turn,
)
from codeflux.settings import Settings, load_config
from codeflux.storage import (
    ClientKeyRepository,
    CredentialVault,
    UsageRepository,
)

logger = logging.getLogger("codeflux.app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = load_config(settings.config_path)
        database = get_shared_database(settings.database_url)
        await database.initialize()
        vault = CredentialVault(database.sessions, settings.master_secret)
        try:
            credentials = json.loads(settings.credentials_json)
            for reference, item in credentials.items():
                await vault.put(reference, item["provider"], item["key"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise RuntimeError(
                "CODEFLUX_CREDENTIALS_JSON must map refs to provider/key objects"
            ) from exc
        # No read limit here: each candidate's timeout_seconds (enforced by the router) decides,
        # so slow local models are not cut off at a fixed 30 seconds.
        limits = httpx.Limits(max_keepalive_connections=50, max_connections=200)
        timeout = httpx.Timeout(timeout=60.0, connect=10.0)
        client = httpx.AsyncClient(limits=limits, timeout=timeout)
        registry = AdapterRegistry(client, config.provider_base_urls)
        breaker = CircuitBreaker(
            config.circuit_breaker.failure_threshold, config.circuit_breaker.cooldown_seconds
        )
        from codeflux.gateway.ratelimit import SlidingWindowRpmLimiter

        app.state.config = config
        app.state.database = database
        app.state.session_factory = getattr(app.state, "session_factory", None) or database.sessions
        app.state.client = client
        app.state.registry = registry
        app.state.breaker = breaker
        app.state.rpm_limiter = SlidingWindowRpmLimiter()
        app.state.client_keys = settings.client_keys()
        app.state.client_key_repository = ClientKeyRepository(
            database.sessions, settings.master_secret
        )
        app.state.usage_repository = UsageRepository(database.sessions)
        app.state.demo_outages = set()
        app.state.settings = settings
        app.state.router = RoutingEngine(
            config, registry, KeyPool(vault), breaker, app.state.usage_repository, PIIRedactor()
        )
        app.state.router.demo_outages = app.state.demo_outages
        yield
        await client.aclose()
        await database.close()

    app = FastAPI(title="CodeFlux", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = None
    app.state.rpm_limiter = SlidingWindowRpmLimiter()
    cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(vault_router)
    app.include_router(keys_router)
    app.include_router(routes_router)
    app.include_router(demo_router)
    app.include_router(member_requests_router)
    app.include_router(member_sessions_router)
    app.include_router(admin_requests_router)
    app.include_router(admin_traces_router)
    app.include_router(admin_usage_router)
    app.include_router(member_usage_router)
    app.include_router(explain_router)
    app.include_router(playground_router)
    app.include_router(arena_router)

    def error_response(status_code: int, message: str, error_type: str) -> JSONResponse:
        # "error" is the shape OpenAI/Gemini SDKs parse; "detail" keeps FastAPI clients working.
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {"message": message, "type": error_type, "code": status_code},
                "detail": message,
            },
        )

    @app.exception_handler(NoProviderAvailable)
    async def no_provider(_: Request, exc: NoProviderAvailable):
        return error_response(503, str(exc), "provider_unavailable")

    @app.exception_handler(ProviderError)
    async def provider_error(_: Request, exc: ProviderError):
        return error_response(
            exc.status_code,
            str(exc),
            "invalid_request_error" if exc.status_code in (400, 422) else "provider_error",
        )

    @app.exception_handler(PermissionError)
    async def forbidden(_: Request, exc: PermissionError):
        return error_response(403, str(exc), "permission_denied")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api"):
            if isinstance(exc.detail, dict):
                code = exc.detail.get("code", "error")
                message = exc.detail.get("message", str(exc.detail))
            else:
                code = "error" if exc.status_code >= 500 else "client_error"
                message = str(exc.detail)
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"code": code, "message": message}},
                headers=exc.headers,
            )
        if isinstance(exc.detail, dict):
            message = exc.detail.get("message", str(exc.detail))
            error_type = exc.detail.get(
                "type",
                {401: "invalid_api_key", 429: "insufficient_quota"}.get(
                    exc.status_code, "invalid_request_error"
                ),
            )
            code = exc.detail.get("code", exc.status_code)
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error": {"message": message, "type": error_type, "code": code},
                    "detail": message,
                },
                headers=exc.headers,
            )
        error_type = {401: "invalid_api_key", 429: "insufficient_quota"}.get(
            exc.status_code, "invalid_request_error"
        )
        return error_response(exc.status_code, str(exc.detail), error_type)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "codeflux"}

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/health/providers")
    async def provider_health(request: Request, _: str = Depends(authenticate)):
        providers = {
            candidate.provider
            for route in request.app.state.config.routes.values()
            for candidate in route.candidates
        }
        results = [
            await request.app.state.registry.get(provider).health_check()
            for provider in sorted(providers)
        ]
        return {
            "providers": [result.model_dump() for result in results],
            "circuits": request.app.state.breaker.snapshot(),
        }

    @app.get("/v1/models")
    async def models(request: Request, team: str = Depends(authenticate)):
        data = []
        for alias, route in request.app.state.config.routes.items():
            if not route.allowed_teams or team in route.allowed_teams:
                data.append(
                    {
                        "id": alias,
                        "object": "model",
                        "owned_by": "codeflux",
                        "providers": sorted({c.provider for c in route.candidates}),
                    }
                )
        return {"object": "list", "data": data}

    @app.get("/v1/me")
    async def me(request: Request, team: str = Depends(authenticate)):
        used = await request.app.state.usage_repository.tokens_this_month(team)
        limit = request.state.client_identity.get("monthly_token_limit")
        return {
            "team": team,
            "name": request.state.client_identity.get("name"),
            "tokens_used_this_month": used,
            "monthly_token_limit": limit,
            "tokens_left_this_month": None if limit is None else max(0, limit - used),
        }

    @app.get("/v1/usage")
    async def usage(request: Request, team: str = Depends(authenticate)):
        return await request.app.state.usage_repository.summary(team)

    async def handle_openai(
        request: Request, operation: str, team: str, background_tasks: BackgroundTasks
    ):
        start_time = time.monotonic()
        try:
            payload = await request.json()
            normalized = openai_request(payload, operation)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        task_tag = request.headers.get("x-omnikey-task")
        custom_fallback = request.headers.get("x-omnikey-fallback")
        platform_key = getattr(request.state, "platform_key", None)
        allowed_routes = platform_key.allowed_routes if platform_key else None
        router = request.app.state.router
        kwargs: dict[str, Any] = {}
        if task_tag is not None:
            kwargs["task_tag"] = task_tag
        if custom_fallback is not None:
            kwargs["custom_fallback"] = custom_fallback
        if allowed_routes is not None:
            kwargs["allowed_routes"] = allowed_routes

        session_id = request.headers.get("x-omnikey-session", "").strip() or None
        session_factory = getattr(request.app.state, "session_factory", None) or getattr(
            getattr(request.app.state, "database", None), "sessions", None
        )
        session_meta = None
        org_id = getattr(request.state, "org_id", None) or "org_default"
        key_id = getattr(request.state, "key_id", None)

        db_session = getattr(request.state, "db_session", None)
        db_source = db_session or session_factory
        if session_id and db_source:
            _, err = await get_or_create_gateway_session(db_source, org_id, key_id, session_id)
            if err:
                raise PermissionError(err)
            if normalized.messages:
                dispatched_messages, session_meta = await prepare_session_messages(
                    db_source, session_id, normalized.messages, normalized.model
                )
                normalized = normalized.model_copy(update={"messages": dispatched_messages})

        if normalized.stream:
            try:
                result = await router.route_stream(
                    normalized,
                    team,
                    **kwargs,
                )
            except TypeError:
                result = await router.route_stream(normalized, team)
            created = int(time.time())

            async def events():
                stream_prompt_tokens = 0
                stream_completion_tokens = 0
                full_chars = 0
                full_content_parts: list[str] = []
                try:
                    async for chunk in result.chunks:
                        if getattr(chunk, "is_error", False) or chunk.finish_reason == "error":
                            yield 'data: {"error": {"message": "Stream interrupted", "type": "stream_error", "code": 500}}\n\n'
                            return
                        if chunk.usage and chunk.usage.total_tokens > 0:
                            stream_prompt_tokens = chunk.usage.prompt_tokens
                            stream_completion_tokens = chunk.usage.completion_tokens
                        if chunk.content:
                            full_chars += len(chunk.content)
                            full_content_parts.append(chunk.content)
                        delta = {}
                        if chunk.content is not None:
                            delta["content"] = chunk.content
                        if chunk.tool_calls:
                            delta["tool_calls"] = chunk.tool_calls
                        data = {
                            "id": chunk.id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": normalized.model,
                            "choices": [
                                {"index": 0, "delta": delta, "finish_reason": chunk.finish_reason}
                            ],
                        }
                        yield f"data: {json.dumps(data)}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as exc:  # noqa: BLE001
                    logger.error("Stream interrupted: %s", exc)
                    yield 'data: {"error": {"message": "Stream interrupted", "type": "stream_error", "code": 500}}\n\n'
                    return

                # Record usage in database
                if stream_prompt_tokens == 0 and stream_completion_tokens == 0 and full_chars > 0:
                    stream_completion_tokens = max(1, full_chars // 4)
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                provider_changed = bool(
                    session_meta
                    and session_meta.last_provider
                    and session_meta.last_provider != result.provider
                )
                assistant_content = "".join(full_content_parts) if full_content_parts else None

                if session_factory:
                    if session_id and session_meta:
                        await save_session_turn(
                            session_factory,
                            session_id=session_id,
                            org_id=org_id,
                            incoming_messages=session_meta.new_incoming_messages,
                            assistant_content=assistant_content,
                            provider=result.provider,
                            model=normalized.model,
                        )
                    trace_facts: dict[str, Any] = {
                        "attempts": getattr(result, "attempt_records", None) or [],
                    }
                    if session_meta:
                        trace_facts.update(
                            {
                                "session_id": session_id,
                                "context_carried": session_meta.context_carried,
                                "messages_sent": session_meta.messages_sent,
                                "messages_trimmed": session_meta.messages_trimmed,
                                "provider_changed": provider_changed,
                            }
                        )
                    await record_usage_and_trace(
                        session_factory,
                        org_id=org_id,
                        key_id=key_id,
                        provider=result.provider,
                        model=normalized.model,
                        status_code=200,
                        latency_ms=elapsed_ms,
                        prompt_tokens=stream_prompt_tokens,
                        completion_tokens=stream_completion_tokens,
                        facts=trace_facts,
                    )

            return StreamingResponse(
                events(),
                media_type="text/event-stream",
                headers={
                    "X-CodeFlux-Provider": result.provider,
                    "X-OmniKey-Provider": result.provider or "",
                    "X-OmniKey-Model": normalized.model or "",
                    "X-OmniKey-Attempts": str(len(result.attempts)),
                },
            )

        try:
            result = await router.route(
                normalized,
                team,
                **kwargs,
            )
        except TypeError:
            result = await router.route(normalized, team)
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        response = to_openai(result.response, operation, normalized.model)
        response["codeflux"] = {"provider": result.provider, "attempts": result.attempts}

        provider_changed = bool(
            session_meta
            and session_meta.last_provider
            and session_meta.last_provider != result.provider
        )
        assistant_content = result.response.content

        # Generate trace id here so we can include it in the X-OmniKey-Trace-Id header.
        import uuid as _uuid

        trace_id = f"trc_{_uuid.uuid4().hex[:28]}"

        if session_factory:
            if session_id and session_meta:
                background_tasks.add_task(
                    save_session_turn,
                    session_factory,
                    session_id=session_id,
                    org_id=org_id,
                    incoming_messages=session_meta.new_incoming_messages,
                    assistant_content=assistant_content,
                    provider=result.provider,
                    model=normalized.model,
                )

            usage = result.response.usage
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0
            trace_facts: dict[str, Any] = {
                "attempts": getattr(result, "attempt_records", None) or [],
            }
            if session_meta:
                trace_facts.update(
                    {
                        "session_id": session_id,
                        "context_carried": session_meta.context_carried,
                        "messages_sent": session_meta.messages_sent,
                        "messages_trimmed": session_meta.messages_trimmed,
                        "provider_changed": provider_changed,
                    }
                )
            background_tasks.add_task(
                record_usage_and_trace,
                session_factory,
                org_id=org_id,
                key_id=key_id,
                provider=result.provider,
                model=normalized.model,
                status_code=200,
                latency_ms=elapsed_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                trace_id=trace_id,
                facts=trace_facts,
            )

        platform_key_state = getattr(request.state, "platform_key", None)
        credits_remaining = (
            str(platform_key_state.credit_remaining_micro) if platform_key_state else ""
        )
        omnikey_headers = {
            "X-OmniKey-Trace-Id": trace_id,
            "X-OmniKey-Provider": result.provider or "",
            "X-OmniKey-Model": normalized.model or "",
            "X-OmniKey-Attempts": str(len(result.attempts)),
            "X-OmniKey-Latency-Ms": str(elapsed_ms),
            "X-OmniKey-Credits-Remaining": credits_remaining,
        }
        return JSONResponse(content=response, headers=omnikey_headers)

    @app.post("/v1/chat/completions")
    async def chat(
        request: Request,
        background_tasks: BackgroundTasks,
        team: str = Depends(authenticate),
    ):
        return await handle_openai(request, "chat", team, background_tasks)

    @app.post("/v1/completions")
    async def completions(
        request: Request,
        background_tasks: BackgroundTasks,
        team: str = Depends(authenticate),
    ):
        return await handle_openai(request, "completion", team, background_tasks)

    @app.post("/v1/embeddings")
    async def embeddings(
        request: Request,
        background_tasks: BackgroundTasks,
        team: str = Depends(authenticate),
    ):
        return await handle_openai(request, "embedding", team, background_tasks)

    @app.post("/v1beta/models/{model}:generateContent")
    @app.post("/v1/models/{model}:generateContent")
    async def generate_content(
        model: str,
        payload: GeminiRequest,
        request: Request,
        background_tasks: BackgroundTasks,
        team: str = Depends(authenticate),
    ):
        start_time = time.monotonic()
        task_tag = request.headers.get("x-omnikey-task")
        custom_fallback = request.headers.get("x-omnikey-fallback")
        platform_key = getattr(request.state, "platform_key", None)
        allowed_routes = platform_key.allowed_routes if platform_key else None
        router = request.app.state.router
        kwargs: dict[str, Any] = {}
        if task_tag is not None:
            kwargs["task_tag"] = task_tag
        if custom_fallback is not None:
            kwargs["custom_fallback"] = custom_fallback
        if allowed_routes is not None:
            kwargs["allowed_routes"] = allowed_routes

        session_id = request.headers.get("x-omnikey-session", "").strip() or None
        session_factory = getattr(request.app.state, "session_factory", None) or getattr(
            getattr(request.app.state, "database", None), "sessions", None
        )
        session_meta = None
        org_id = getattr(request.state, "org_id", None) or "org_default"
        key_id = getattr(request.state, "key_id", None)

        db_session = getattr(request.state, "db_session", None)
        db_source = db_session or session_factory
        normalized = gemini_request(model, payload)
        if session_id and db_source:
            _, err = await get_or_create_gateway_session(db_source, org_id, key_id, session_id)
            if err:
                raise PermissionError(err)
            if normalized.messages:
                dispatched_messages, session_meta = await prepare_session_messages(
                    db_source, session_id, normalized.messages, model
                )
                normalized = normalized.model_copy(update={"messages": dispatched_messages})

        try:
            result = await router.route(
                normalized,
                team,
                **kwargs,
            )
        except TypeError:
            result = await router.route(normalized, team)
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        gemini_resp = to_gemini(result.response)

        provider_changed = bool(
            session_meta
            and session_meta.last_provider
            and session_meta.last_provider != result.provider
        )
        assistant_content = result.response.content

        if session_factory:
            if session_id and session_meta:
                background_tasks.add_task(
                    save_session_turn,
                    session_factory,
                    session_id=session_id,
                    org_id=org_id,
                    incoming_messages=session_meta.new_incoming_messages,
                    assistant_content=assistant_content,
                    provider=result.provider,
                    model=model,
                )

            usage = result.response.usage
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0
            trace_facts: dict[str, Any] = {
                "attempts": getattr(result, "attempt_records", None) or [],
            }
            if session_meta:
                trace_facts.update(
                    {
                        "session_id": session_id,
                        "context_carried": session_meta.context_carried,
                        "messages_sent": session_meta.messages_sent,
                        "messages_trimmed": session_meta.messages_trimmed,
                        "provider_changed": provider_changed,
                    }
                )
            background_tasks.add_task(
                record_usage_and_trace,
                session_factory,
                org_id=org_id,
                key_id=key_id,
                provider=result.provider,
                model=model,
                status_code=200,
                latency_ms=elapsed_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                facts=trace_facts,
            )

        platform_key_state = getattr(request.state, "platform_key", None)
        credits_remaining = (
            str(platform_key_state.credit_remaining_micro) if platform_key_state else ""
        )
        gemini_headers = {
            "X-OmniKey-Provider": result.provider or "",
            "X-OmniKey-Model": model or "",
            "X-OmniKey-Attempts": str(len(result.attempts)),
            "X-OmniKey-Latency-Ms": str(elapsed_ms),
            "X-OmniKey-Credits-Remaining": credits_remaining,
        }
        return JSONResponse(content=gemini_resp, headers=gemini_headers)

    @app.post("/v1beta/models/{model}:streamGenerateContent")
    @app.post("/v1/models/{model}:streamGenerateContent")
    async def stream_generate_content(
        model: str,
        payload: GeminiRequest,
        request: Request,
        alt: str | None = None,
        team: str = Depends(authenticate),
    ):
        task_tag = request.headers.get("x-omnikey-task")
        custom_fallback = request.headers.get("x-omnikey-fallback")
        platform_key = getattr(request.state, "platform_key", None)
        allowed_routes = platform_key.allowed_routes if platform_key else None
        router = request.app.state.router
        kwargs: dict[str, Any] = {}
        if task_tag is not None:
            kwargs["task_tag"] = task_tag
        if custom_fallback is not None:
            kwargs["custom_fallback"] = custom_fallback
        if allowed_routes is not None:
            kwargs["allowed_routes"] = allowed_routes

        normalized = gemini_request(model, payload).model_copy(update={"stream": True})
        try:
            result = await router.route_stream(
                normalized,
                team,
                **kwargs,
            )
        except TypeError:
            result = await router.route_stream(normalized, team)
        headers = {"X-CodeFlux-Provider": result.provider}
        if alt == "sse":

            async def events():
                async for chunk in result.chunks:
                    yield f"data: {json.dumps(gemini_chunk(chunk))}\r\n\r\n"

            return StreamingResponse(events(), media_type="text/event-stream", headers=headers)
        # Without alt=sse the Gemini REST API streams one JSON array.
        chunks = [gemini_chunk(chunk) async for chunk in result.chunks]
        return JSONResponse(chunks, headers=headers)

    @app.get("/metrics", response_class=Response)
    async def metrics(_: str = Depends(authenticate)):
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/dashboard/status")
    async def dashboard_status(request: Request, _: str = Depends(authenticate)):
        router = request.app.state.router
        return {
            "last_route": router.last_route,
            "limits": router.key_pool.snapshot(),
            "circuits": request.app.state.breaker.snapshot(),
        }

    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    is_test = getattr(settings, "env", "dev").strip().lower() in ("test", "testing")
    if not is_test and frontend_dist.exists():
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            if full_path.startswith(("api", "v1", "health", "metrics", "dashboard")):
                raise HTTPException(status_code=404, detail="Not found")
            index_file = frontend_dist / "index.html"
            if index_file.exists():
                return FileResponse(index_file)
            return JSONResponse({"status": "frontend_not_built"}, status_code=404)

    return app


app = create_app()
