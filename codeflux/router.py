from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass

from codeflux.adapters.registry import AdapterRegistry
from codeflux.circuit import CircuitBreaker
from codeflux.config import AppConfig, CandidateConfig, RouteConfig
from codeflux.errors import NoProviderAvailable
from codeflux.keys import KeyPool
from codeflux.metrics import CIRCUITS, FAILOVERS, LATENCY, REQUESTS, TOKENS
from codeflux.pii import PIIRedactor
from codeflux.schemas import NormalizedRequest, NormalizedResponse, StreamChunk
from codeflux.storage import UsageRepository

logger = logging.getLogger("codeflux.router")


@dataclass
class RoutingResult:
    response: NormalizedResponse
    provider: str
    key_ref: str | None
    attempts: list[str]


@dataclass
class StreamingRoutingResult:
    chunks: AsyncIterator[StreamChunk]
    provider: str
    attempts: list[str]


class RoutingEngine:
    def __init__(self, config: AppConfig, registry: AdapterRegistry, key_pool: KeyPool, circuits: CircuitBreaker, usage: UsageRepository, redactor: PIIRedactor | None = None):
        self.config, self.registry, self.key_pool = config, registry, key_pool
        self.circuits, self.usage, self.redactor = circuits, usage, redactor or PIIRedactor()
        self._round_robin: defaultdict[str, int] = defaultdict(int)
        self._latencies: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=50))
        self.last_route: dict[str, object] | None = None

    def _ordered(self, alias: str, route: RouteConfig) -> list[CandidateConfig]:
        candidates = list(route.candidates)
        if route.strategy == "round-robin":
            offset = self._round_robin[alias] % len(candidates)
            self._round_robin[alias] += 1
            return candidates[offset:] + candidates[:offset]
        if route.strategy == "least-latency":
            return sorted(candidates, key=lambda c: sum(self._latencies[c.provider]) / len(self._latencies[c.provider]) if self._latencies[c.provider] else float("inf"))
        if route.strategy == "weighted-random":
            result = []
            while candidates:
                chosen = random.choices(candidates, weights=[item.weight for item in candidates], k=1)[0]
                result.append(chosen)
                candidates.remove(chosen)
            return result
        return candidates

    async def route(self, request: NormalizedRequest, team: str) -> RoutingResult:
        route = self.config.routes.get(request.model)
        if not route:
            raise NoProviderAvailable(f"no route configured for model alias '{request.model}'")
        if route.allowed_teams and team not in route.allowed_teams:
            raise PermissionError(f"team '{team}' cannot access route '{request.model}'")
        outgoing = self.redactor.redact(request) if route.pii_redaction else request
        candidates = self._ordered(request.model, route)
        if route.ollama_fallback_model and not any(item.provider == "ollama" for item in candidates):
            candidates.append(
                CandidateConfig(
                    provider="ollama",
                    model=route.ollama_fallback_model,
                    timeout_seconds=route.ollama_fallback_timeout_seconds,
                )
            )
        deadline = time.monotonic() + route.total_timeout_seconds
        attempts: list[str] = []
        last_error: Exception | None = None
        for candidate in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            key_ref, api_key = await self.key_pool.select(candidate.provider, candidate.api_key_ref)
            if not api_key and candidate.provider != "ollama":
                logger.warning("no_key_available", extra={"route": request.model, "provider": candidate.provider})
                attempts.append(f"{candidate.provider}:no-key")
                continue
            identity = f"{candidate.provider}:{key_ref or 'anonymous'}"
            if not await self.circuits.allow(identity):
                CIRCUITS.labels(identity).set(1)
                attempts.append(f"{candidate.provider}:circuit-open")
                continue
            adapter = self.registry.get(candidate.provider)
            provider_request = outgoing.model_copy(update={"model": candidate.model})
            attempts.append(candidate.provider)
            started = time.monotonic()
            try:
                response = await asyncio.wait_for(adapter.chat_completion(provider_request, api_key), timeout=min(remaining, candidate.timeout_seconds))
                await self.key_pool.update_limits(key_ref, response.rate_limit_headers)
                elapsed = time.monotonic() - started
                self._latencies[candidate.provider].append(elapsed)
                LATENCY.labels(candidate.provider).observe(elapsed)
                await self.circuits.success(identity)
                CIRCUITS.labels(identity).set(0)
                REQUESTS.labels(request.model, candidate.provider, "success").inc()
                TOKENS.labels(candidate.provider, "prompt", key_ref or "anonymous").inc(response.usage.prompt_tokens)
                TOKENS.labels(candidate.provider, "completion", key_ref or "anonymous").inc(response.usage.completion_tokens)
                await self.usage.record(team=team, provider=candidate.provider, key_ref=key_ref, model=candidate.model, prompt_tokens=response.usage.prompt_tokens, completion_tokens=response.usage.completion_tokens)
                self.last_route = {"alias": request.model, "provider": candidate.provider, "model": candidate.model, "key_ref": key_ref, "team": team, "attempts": list(attempts)}
                logger.info("request_complete", extra={"route": request.model, "provider": candidate.provider, "latency_ms": round(elapsed * 1000, 2), "attempts": attempts, "team": team})
                return RoutingResult(response=response, provider=candidate.provider, key_ref=key_ref, attempts=attempts)
            except Exception as exc:  # noqa: BLE001 - adapters may raise vendor SDK exceptions
                last_error = exc
                await self.circuits.failure(identity)
                FAILOVERS.labels(candidate.provider, type(exc).__name__).inc()
                REQUESTS.labels(request.model, candidate.provider, "error").inc()
                logger.warning("provider_failed", extra={"route": request.model, "provider": candidate.provider, "error": str(exc), "attempts": len(attempts)})
        raise NoProviderAvailable(f"all providers failed for '{request.model}': {last_error or 'timeout/circuit open'}")

    async def route_stream(self, request: NormalizedRequest, team: str) -> StreamingRoutingResult:
        """Choose a provider by obtaining its first chunk, allowing pre-stream failover."""
        route = self.config.routes.get(request.model)
        if not route:
            raise NoProviderAvailable(f"no route configured for model alias '{request.model}'")
        if route.allowed_teams and team not in route.allowed_teams:
            raise PermissionError(f"team '{team}' cannot access route '{request.model}'")
        candidates = self._ordered(request.model, route)
        if route.ollama_fallback_model and not any(c.provider == "ollama" for c in candidates):
            candidates.append(
                CandidateConfig(
                    provider="ollama",
                    model=route.ollama_fallback_model,
                    timeout_seconds=route.ollama_fallback_timeout_seconds,
                )
            )
        attempts: list[str] = []
        deadline = time.monotonic() + route.total_timeout_seconds
        for candidate in candidates:
            key_ref, api_key = await self.key_pool.select(candidate.provider, candidate.api_key_ref)
            if not api_key and candidate.provider != "ollama":
                logger.warning("no_key_available", extra={"route": request.model, "provider": candidate.provider})
                attempts.append(f"{candidate.provider}:no-key")
                continue
            identity = f"{candidate.provider}:{key_ref or 'anonymous'}"
            if not await self.circuits.allow(identity):
                continue
            attempts.append(candidate.provider)
            stream = self.registry.get(candidate.provider).stream_chat_completion(
                request.model_copy(update={"model": candidate.model, "stream": True}), api_key
            )
            try:
                first = await asyncio.wait_for(anext(stream), timeout=min(candidate.timeout_seconds, max(0.01, deadline - time.monotonic())))
                await self.circuits.success(identity)
                self.last_route = {"alias": request.model, "provider": candidate.provider, "model": candidate.model, "key_ref": key_ref, "team": team, "attempts": list(attempts), "streaming": True}

                async def with_first(
                    initial=first,
                    upstream=stream,
                    provider=candidate.provider,
                    selected_key_ref=key_ref,
                    selected_model=candidate.model,
                    selected_team=team,
                ) -> AsyncIterator[StreamChunk]:
                    final_usage = initial.usage
                    try:
                        yield initial
                        async for chunk in upstream:
                            if chunk.usage is not None:
                                final_usage = chunk.usage
                            yield chunk
                    finally:
                        if final_usage is not None:
                            TOKENS.labels(provider, "prompt", selected_key_ref or "anonymous").inc(final_usage.prompt_tokens)
                            TOKENS.labels(provider, "completion", selected_key_ref or "anonymous").inc(final_usage.completion_tokens)
                            await self.usage.record(
                                team=selected_team, provider=provider, key_ref=selected_key_ref,
                                model=selected_model, prompt_tokens=final_usage.prompt_tokens,
                                completion_tokens=final_usage.completion_tokens,
                            )

                return StreamingRoutingResult(with_first(), candidate.provider, attempts)
            except Exception as exc:  # noqa: BLE001 - adapters may raise vendor SDK exceptions
                await self.circuits.failure(identity)
                FAILOVERS.labels(candidate.provider, type(exc).__name__).inc()
        raise NoProviderAvailable(f"all streaming providers failed for '{request.model}'")
