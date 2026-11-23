from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException

from codeflux.api import (
    admin_requests_router,
    auth_router,
    keys_router,
    member_requests_router,
    routes_router,
    vault_router,
)
from codeflux.errors import NoProviderAvailable
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
from codeflux.providers.registry import AdapterRegistry
from codeflux.schemas import GeminiRequest
from codeflux.settings import Settings, load_config
from codeflux.storage import (
    ClientKeyRepository,
    CredentialVault,
    Database,
    UsageRepository,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = load_config(settings.config_path)
        database = Database(settings.database_url)
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
        app.state.client = client
        app.state.registry = registry
        app.state.breaker = breaker
        app.state.rpm_limiter = SlidingWindowRpmLimiter()
        app.state.client_keys = settings.client_keys()
        app.state.client_key_repository = ClientKeyRepository(
            database.sessions, settings.master_secret
        )
        app.state.usage_repository = UsageRepository(database.sessions)
        app.state.router = RoutingEngine(
            config, registry, KeyPool(vault), breaker, app.state.usage_repository, PIIRedactor()
        )
        yield
        await client.aclose()
        await database.close()

    app = FastAPI(title="CodeFlux", version="0.1.0", lifespan=lifespan)
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
    app.include_router(member_requests_router)
    app.include_router(admin_requests_router)

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

    async def handle_openai(request: Request, operation: str, team: str):
        try:
            payload = await request.json()
            normalized = openai_request(payload, operation)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if normalized.stream:
            result = await request.app.state.router.route_stream(normalized, team)
            created = int(time.time())

            async def events():
                async for chunk in result.chunks:
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

            return StreamingResponse(
                events(),
                media_type="text/event-stream",
                headers={"X-CodeFlux-Provider": result.provider},
            )
        result = await request.app.state.router.route(normalized, team)
        response = to_openai(result.response, operation, normalized.model)
        response["codeflux"] = {"provider": result.provider, "attempts": result.attempts}
        return response

    @app.post("/v1/chat/completions")
    async def chat(request: Request, team: str = Depends(authenticate)):
        return await handle_openai(request, "chat", team)

    @app.post("/v1/completions")
    async def completions(request: Request, team: str = Depends(authenticate)):
        return await handle_openai(request, "completion", team)

    @app.post("/v1/embeddings")
    async def embeddings(request: Request, team: str = Depends(authenticate)):
        return await handle_openai(request, "embedding", team)

    @app.post("/v1beta/models/{model}:generateContent")
    @app.post("/v1/models/{model}:generateContent")
    async def generate_content(
        model: str, payload: GeminiRequest, request: Request, team: str = Depends(authenticate)
    ):
        result = await request.app.state.router.route(gemini_request(model, payload), team)
        return to_gemini(result.response)

    @app.post("/v1beta/models/{model}:streamGenerateContent")
    @app.post("/v1/models/{model}:streamGenerateContent")
    async def stream_generate_content(
        model: str,
        payload: GeminiRequest,
        request: Request,
        alt: str | None = None,
        team: str = Depends(authenticate),
    ):
        normalized = gemini_request(model, payload).model_copy(update={"stream": True})
        result = await request.app.state.router.route_stream(normalized, team)
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

    return app


app = create_app()
