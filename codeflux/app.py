from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from codeflux.adapters.registry import AdapterRegistry
from codeflux.auth import authenticate
from codeflux.circuit import CircuitBreaker
from codeflux.config import Settings, load_config
from codeflux.errors import NoProviderAvailable
from codeflux.keys import KeyPool
from codeflux.logging import configure_logging
from codeflux.normalization import gemini_request, openai_request, to_gemini, to_openai
from codeflux.pii import PIIRedactor
from codeflux.router import RoutingEngine
from codeflux.schemas import GeminiRequest
from codeflux.storage import CredentialVault, Database, UsageRepository


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
            raise RuntimeError("CODEFLUX_CREDENTIALS_JSON must map refs to provider/key objects") from exc
        client = httpx.AsyncClient(timeout=30)
        registry = AdapterRegistry(client, config.provider_base_urls)
        breaker = CircuitBreaker(config.circuit_breaker.failure_threshold, config.circuit_breaker.cooldown_seconds)
        app.state.config = config
        app.state.database = database
        app.state.client = client
        app.state.registry = registry
        app.state.breaker = breaker
        app.state.client_keys = settings.client_keys()
        app.state.router = RoutingEngine(config, registry, KeyPool(vault), breaker, UsageRepository(database.sessions), PIIRedactor())
        yield
        await client.aclose()
        await database.close()

    app = FastAPI(title="CodeFlux", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(NoProviderAvailable)
    async def no_provider(_: Request, exc: NoProviderAvailable):
        return JSONResponse(status_code=503, content={"error": {"message": str(exc), "type": "provider_unavailable"}})

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "codeflux"}

    @app.get("/health/providers")
    async def provider_health(request: Request, _: str = Depends(authenticate)):
        providers = {candidate.provider for route in request.app.state.config.routes.values() for candidate in route.candidates}
        results = [await request.app.state.registry.get(provider).health_check() for provider in sorted(providers)]
        return {"providers": [result.model_dump() for result in results], "circuits": request.app.state.breaker.snapshot()}

    @app.get("/v1/models")
    async def models(request: Request, team: str = Depends(authenticate)):
        data = []
        for alias, route in request.app.state.config.routes.items():
            if not route.allowed_teams or team in route.allowed_teams:
                data.append({"id": alias, "object": "model", "owned_by": "codeflux", "providers": sorted({c.provider for c in route.candidates})})
        return {"object": "list", "data": data}

    async def handle_openai(request: Request, operation: str, team: str):
        try:
            payload = await request.json()
            normalized = openai_request(payload, operation)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if normalized.stream:
            result = await request.app.state.router.route_stream(normalized, team)

            async def events():
                async for chunk in result.chunks:
                    data = {"id": chunk.id, "object": "chat.completion.chunk", "model": normalized.model, "choices": [{"index": 0, "delta": {"content": chunk.content} if chunk.content is not None else {}, "finish_reason": chunk.finish_reason}]}
                    yield f"data: {json.dumps(data)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(events(), media_type="text/event-stream", headers={"X-CodeFlux-Provider": result.provider})
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
    async def generate_content(model: str, payload: GeminiRequest, request: Request, team: str = Depends(authenticate)):
        result = await request.app.state.router.route(gemini_request(model, payload), team)
        return to_gemini(result.response)

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
