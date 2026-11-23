from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from codeflux.errors import NoProviderAvailable, ProviderError
from codeflux.gateway.circuit import CircuitBreaker
from codeflux.gateway.keypool import KeyPool
from codeflux.gateway.pii import PIIRedactor
from codeflux.metrics import CIRCUITS, FAILOVERS, LATENCY, REQUESTS, TOKENS
from codeflux.providers.registry import AdapterRegistry
from codeflux.schemas import NormalizedRequest, NormalizedResponse, StreamChunk, Usage
from codeflux.settings import AppConfig, CandidateConfig, RouteConfig
from codeflux.storage import UsageRepository

logger = logging.getLogger("codeflux.router")


def _is_embedding_route(route: RouteConfig) -> bool:
    return all("embed" in candidate.model for candidate in route.candidates)


def _parse_custom_fallback(custom_fallback: str) -> list[CandidateConfig]:
    candidates: list[CandidateConfig] = []
    for item in custom_fallback.split(","):
        item = item.strip()
        if not item:
            continue
        if "/" in item:
            provider, model = item.split("/", 1)
        elif ":" in item:
            provider, model = item.split(":", 1)
        else:
            provider, model = "openai", item
        candidates.append(CandidateConfig(provider=provider.strip(), model=model.strip()))
    return candidates


@dataclass
class RoutingResult:
    response: NormalizedResponse
    provider: str
    key_ref: str | None
    attempts: list[str]
    attempt_records: list[dict[str, Any]] | None = None


@dataclass
class StreamingRoutingResult:
    chunks: AsyncIterator[StreamChunk]
    provider: str
    attempts: list[str]
    attempt_records: list[dict[str, Any]] | None = None


class RoutingEngine:
    def __init__(
        self,
        config: AppConfig,
        registry: AdapterRegistry,
        key_pool: KeyPool,
        circuits: CircuitBreaker,
        usage: UsageRepository,
        redactor: PIIRedactor | None = None,
    ):
        self.config, self.registry, self.key_pool = config, registry, key_pool
        self.circuits, self.usage, self.redactor = circuits, usage, redactor or PIIRedactor()
        self._round_robin: defaultdict[str, int] = defaultdict(int)
        self._latencies: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=50))
        self.demo_outages: set[str] = set()
        self.last_attempts: list[dict[str, Any]] = []
        self.last_route: dict[str, object] | None = None

    def resolve(
        self,
        model: str,
        operation: str = "chat",
        *,
        task_tag: str | None = None,
        custom_fallback: str | None = None,
        allowed_routes: list[str] | None = None,
    ) -> tuple[str, RouteConfig]:
        """Map any model name and overrides onto a configured route.

        Checks task_tag header, model alias, candidate models, concrete model
        with default route fallback, and enforces allowed_routes.
        """
        routes = self.config.routes
        alias: str | None = None
        route: RouteConfig | None = None

        # 1. Task tag override
        if task_tag:
            for r_alias, r_cfg in routes.items():
                if getattr(r_cfg, "task_tag", None) == task_tag:
                    alias = r_alias
                    route = r_cfg
                    break

        # 2. Model resolution
        if route is None:
            name = model.removeprefix("models/")
            if name in routes:
                alias = name
                route = routes[name]
            else:
                wants_embedding = operation == "embedding"
                for r_alias, r_cfg in routes.items():
                    if _is_embedding_route(r_cfg) != wants_embedding:
                        continue
                    matching = [
                        c
                        for c in r_cfg.candidates
                        if c.model == name or f"{c.provider}/{c.model}" == name
                    ]
                    if matching:
                        others = [c for c in r_cfg.candidates if c not in matching]
                        alias = r_alias
                        route = r_cfg.model_copy(update={"candidates": matching + others})
                        break

                if route is None:
                    default = (
                        self.config.default_embedding_route
                        if wants_embedding
                        else self.config.default_route
                    )
                    default_route_cfg = routes.get(default) if default else None
                    if default_route_cfg is None:
                        for r_alias, r_cfg in routes.items():
                            if _is_embedding_route(r_cfg) == wants_embedding:
                                default = r_alias
                                default_route_cfg = r_cfg
                                break

                    if "/" in name:
                        provider_part, model_part = name.split("/", 1)
                        concrete_candidate = CandidateConfig(
                            provider=provider_part, model=model_part
                        )
                        fallback_candidates = []
                        if default_route_cfg:
                            fallback_candidates = [
                                c
                                for c in default_route_cfg.candidates
                                if not (c.provider == provider_part and c.model == model_part)
                            ]
                        alias = default or "default"
                        route = RouteConfig(
                            candidates=[concrete_candidate] + fallback_candidates,
                            strategy=default_route_cfg.strategy
                            if default_route_cfg
                            else "priority",
                        )
                    elif default_route_cfg is not None:
                        alias = default
                        route = default_route_cfg
                    else:
                        raise NoProviderAvailable(f"no route configured for model '{model}'")

        # 3. Check allowed_routes if restricted
        if (
            allowed_routes
            and "*" not in allowed_routes
            and alias not in allowed_routes
            and model not in allowed_routes
        ):
            raise PermissionError(f"model or route '{model}' is not allowed for this key")

        # 4. Custom fallback override
        if custom_fallback:
            custom_candidates = _parse_custom_fallback(custom_fallback)
            if custom_candidates:
                route = route.model_copy(update={"candidates": custom_candidates})

        return alias or "default", route

    def _ordered(self, alias: str, route: RouteConfig) -> list[CandidateConfig]:
        candidates = list(route.candidates)
        if route.strategy == "round-robin":
            offset = self._round_robin[alias] % len(candidates)
            self._round_robin[alias] += 1
            return candidates[offset:] + candidates[:offset]
        if route.strategy == "least-latency":
            return sorted(
                candidates,
                key=lambda c: (
                    sum(self._latencies[c.provider]) / len(self._latencies[c.provider])
                    if self._latencies[c.provider]
                    else float("inf")
                ),
            )
        if route.strategy == "weighted-random":
            result = []
            while candidates:
                chosen = random.choices(
                    candidates, weights=[item.weight for item in candidates], k=1
                )[0]
                result.append(chosen)
                candidates.remove(chosen)
            return result
        return candidates

    async def route(
        self,
        request: NormalizedRequest,
        team: str,
        *,
        task_tag: str | None = None,
        custom_fallback: str | None = None,
        allowed_routes: list[str] | None = None,
    ) -> RoutingResult:
        alias, route = self.resolve(
            request.model,
            request.operation,
            task_tag=task_tag,
            custom_fallback=custom_fallback,
            allowed_routes=allowed_routes,
        )
        if route.allowed_teams and team not in route.allowed_teams:
            raise PermissionError(f"team '{team}' cannot access route '{alias}'")
        outgoing = self.redactor.redact(request) if route.pii_redaction else request
        candidates = self._ordered(alias, route)
        if route.ollama_fallback_model and not any(
            item.provider == "ollama" for item in candidates
        ):
            candidates.append(
                CandidateConfig(
                    provider="ollama",
                    model=route.ollama_fallback_model,
                    timeout_seconds=route.ollama_fallback_timeout_seconds,
                )
            )
        deadline = time.monotonic() + route.total_timeout_seconds
        attempts: list[str] = []
        attempt_records: list[dict[str, Any]] = []
        last_error: Exception | None = None
        outages = self.demo_outages

        for candidate in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            key_ref, api_key = await self.key_pool.select(candidate.provider, candidate.api_key_ref)
            key_hint = (
                f"...{api_key[-4:]}" if api_key and len(api_key) >= 4 else (key_ref or "none")
            )

            if not api_key and candidate.provider != "ollama":
                logger.warning(
                    "no_key_available",
                    extra={"route": request.model, "provider": candidate.provider},
                )
                attempts.append(f"{candidate.provider}:no-key")
                attempt_records.append(
                    {
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "key_hint": key_hint,
                        "outcome": "skipped",
                        "status_code": None,
                        "latency_ms": 0,
                        "reason_code": "no_key",
                    }
                )
                continue

            identity = f"{candidate.provider}:{key_ref or 'anonymous'}"
            if not await self.circuits.allow(identity):
                CIRCUITS.labels(identity).set(1)
                attempts.append(f"{candidate.provider}:circuit-open")
                attempt_records.append(
                    {
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "key_hint": key_hint,
                        "outcome": "skipped",
                        "status_code": None,
                        "latency_ms": 0,
                        "reason_code": "circuit_open",
                    }
                )
                continue

            # Check demo simulated outage
            if candidate.provider.lower() in outages:
                attempts.append(candidate.provider)
                attempt_records.append(
                    {
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "key_hint": key_hint,
                        "outcome": "failed",
                        "status_code": 429,
                        "latency_ms": 1,
                        "reason_code": "rate_limited",
                    }
                )
                await self.circuits.failure(identity)
                await self.key_pool.set_cooldown(key_ref, 30.0)
                FAILOVERS.labels(candidate.provider, "SimulatedOutage").inc()
                REQUESTS.labels(request.model, candidate.provider, "error").inc()
                continue

            adapter = self.registry.get(candidate.provider)
            provider_request = outgoing.model_copy(update={"model": candidate.model})
            attempts.append(candidate.provider)
            started = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    adapter.chat_completion(provider_request, api_key),
                    timeout=min(remaining, candidate.timeout_seconds),
                )
                elapsed = time.monotonic() - started
                elapsed_ms = int(elapsed * 1000)

                if response.usage.total_tokens == 0:
                    prompt_chars = sum(len(str(m.content or "")) for m in request.messages)
                    if request.prompt:
                        prompt_chars += len(str(request.prompt))
                    completion_chars = len(str(response.content or ""))
                    p_tok = max(1, prompt_chars // 4)
                    c_tok = max(1, completion_chars // 4) if completion_chars else 0
                    response.usage = Usage(
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        total_tokens=p_tok + c_tok,
                        estimated=True,
                    )

                await self.key_pool.update_limits(key_ref, response.rate_limit_headers)
                self._latencies[candidate.provider].append(elapsed)
                LATENCY.labels(candidate.provider).observe(elapsed)
                await self.circuits.success(identity)
                CIRCUITS.labels(identity).set(0)
                REQUESTS.labels(request.model, candidate.provider, "success").inc()
                TOKENS.labels(candidate.provider, "prompt", key_ref or "anonymous").inc(
                    response.usage.prompt_tokens
                )
                TOKENS.labels(candidate.provider, "completion", key_ref or "anonymous").inc(
                    response.usage.completion_tokens
                )
                await self.usage.record(
                    team=team,
                    provider=candidate.provider,
                    key_ref=key_ref,
                    model=candidate.model,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                )

                attempt_records.append(
                    {
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "key_hint": key_hint,
                        "outcome": "succeeded",
                        "status_code": 200,
                        "latency_ms": elapsed_ms,
                        "reason_code": "ok",
                    }
                )

                self.last_attempts = list(attempt_records)
                self.last_route = {
                    "alias": request.model,
                    "provider": candidate.provider,
                    "model": candidate.model,
                    "key_ref": key_ref,
                    "team": team,
                    "attempts": list(attempts),
                    "attempt_records": list(attempt_records),
                }
                logger.info(
                    "request_complete",
                    extra={
                        "route": request.model,
                        "provider": candidate.provider,
                        "latency_ms": elapsed_ms,
                        "attempts": attempts,
                        "team": team,
                    },
                )
                return RoutingResult(
                    response=response,
                    provider=candidate.provider,
                    key_ref=key_ref,
                    attempts=attempts,
                    attempt_records=attempt_records,
                )
            except Exception as exc:  # noqa: BLE001 - adapters may raise vendor SDK exceptions
                elapsed_ms = int((time.monotonic() - started) * 1000)
                last_error = exc

                status_code: int | None = getattr(exc, "status_code", None)
                if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
                    reason_code = "timeout"
                    status_code = status_code or 408
                elif status_code == 429:
                    reason_code = "rate_limited"
                elif status_code == 401:
                    reason_code = "auth_failure"
                elif status_code and status_code in (400, 422):
                    reason_code = "bad_request"
                elif status_code and status_code >= 500:
                    reason_code = "server_error"
                elif any(
                    k in str(exc).lower()
                    for k in ("transport", "connect", "network", "clientconnect")
                ):
                    reason_code = "network_error"
                else:
                    reason_code = "server_error"

                attempt_records.append(
                    {
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "key_hint": key_hint,
                        "outcome": "failed",
                        "status_code": status_code
                        or (502 if reason_code == "network_error" else 500),
                        "latency_ms": elapsed_ms,
                        "reason_code": reason_code,
                    }
                )
                self.last_attempts = list(attempt_records)

                # Client 400 check: NEVER FALL THROUGH ON 400!
                if reason_code == "bad_request" or status_code in (400, 422):
                    if not isinstance(exc, ProviderError):
                        err = ProviderError(str(exc), status_code=400, retryable=False)
                    else:
                        err = exc
                    err.attempt_records = attempt_records  # type: ignore[attr-defined]
                    err.attempts = attempts  # type: ignore[attr-defined]
                    raise err

                await self.circuits.failure(identity)
                if reason_code == "rate_limited":
                    await self.key_pool.set_cooldown(key_ref, 30.0)
                elif reason_code == "auth_failure":
                    await self.key_pool.disable(key_ref)

                FAILOVERS.labels(candidate.provider, type(exc).__name__).inc()
                REQUESTS.labels(request.model, candidate.provider, "error").inc()
                logger.warning(
                    "provider_failed",
                    extra={
                        "route": request.model,
                        "provider": candidate.provider,
                        "error": str(exc),
                        "attempts": len(attempts),
                    },
                )
        raise NoProviderAvailable(
            f"all providers failed for '{request.model}' (tried: {', '.join(attempts) or 'none'}): "
            f"{last_error or 'timeout/circuit open'}"
        )

    async def route_stream(
        self,
        request: NormalizedRequest,
        team: str,
        *,
        task_tag: str | None = None,
        custom_fallback: str | None = None,
        allowed_routes: list[str] | None = None,
    ) -> StreamingRoutingResult:
        """Choose a provider by obtaining its first chunk, allowing pre-stream failover."""
        alias, route = self.resolve(
            request.model,
            request.operation,
            task_tag=task_tag,
            custom_fallback=custom_fallback,
            allowed_routes=allowed_routes,
        )
        if route.allowed_teams and team not in route.allowed_teams:
            raise PermissionError(f"team '{team}' cannot access route '{alias}'")
        outgoing = self.redactor.redact(request) if route.pii_redaction else request
        candidates = self._ordered(alias, route)
        if route.ollama_fallback_model and not any(c.provider == "ollama" for c in candidates):
            candidates.append(
                CandidateConfig(
                    provider="ollama",
                    model=route.ollama_fallback_model,
                    timeout_seconds=route.ollama_fallback_timeout_seconds,
                )
            )
        attempts: list[str] = []
        attempt_records: list[dict[str, Any]] = []
        deadline = time.monotonic() + route.total_timeout_seconds
        outages = self.demo_outages

        for candidate in candidates:
            key_ref, api_key = await self.key_pool.select(candidate.provider, candidate.api_key_ref)
            key_hint = (
                f"...{api_key[-4:]}" if api_key and len(api_key) >= 4 else (key_ref or "none")
            )

            if not api_key and candidate.provider != "ollama":
                logger.warning(
                    "no_key_available",
                    extra={"route": request.model, "provider": candidate.provider},
                )
                attempts.append(f"{candidate.provider}:no-key")
                attempt_records.append(
                    {
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "key_hint": key_hint,
                        "outcome": "skipped",
                        "status_code": None,
                        "latency_ms": 0,
                        "reason_code": "no_key",
                    }
                )
                continue

            identity = f"{candidate.provider}:{key_ref or 'anonymous'}"
            if not await self.circuits.allow(identity):
                attempts.append(f"{candidate.provider}:circuit-open")
                attempt_records.append(
                    {
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "key_hint": key_hint,
                        "outcome": "skipped",
                        "status_code": None,
                        "latency_ms": 0,
                        "reason_code": "circuit_open",
                    }
                )
                continue

            if candidate.provider.lower() in outages:
                attempts.append(candidate.provider)
                attempt_records.append(
                    {
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "key_hint": key_hint,
                        "outcome": "failed",
                        "status_code": 429,
                        "latency_ms": 1,
                        "reason_code": "rate_limited",
                    }
                )
                await self.circuits.failure(identity)
                await self.key_pool.set_cooldown(key_ref, 30.0)
                continue

            attempts.append(candidate.provider)
            stream = self.registry.get(candidate.provider).stream_chat_completion(
                outgoing.model_copy(update={"model": candidate.model, "stream": True}), api_key
            )
            started = time.monotonic()
            try:
                first = await asyncio.wait_for(
                    anext(stream),
                    timeout=min(candidate.timeout_seconds, max(0.01, deadline - time.monotonic())),
                )
                elapsed_ms = int((time.monotonic() - started) * 1000)
                await self.circuits.success(identity)

                attempt_records.append(
                    {
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "key_hint": key_hint,
                        "outcome": "succeeded",
                        "status_code": 200,
                        "latency_ms": elapsed_ms,
                        "reason_code": "ok",
                    }
                )
                self.last_attempts = list(attempt_records)
                self.last_route = {
                    "alias": request.model,
                    "provider": candidate.provider,
                    "model": candidate.model,
                    "key_ref": key_ref,
                    "team": team,
                    "attempts": list(attempts),
                    "attempt_records": list(attempt_records),
                    "streaming": True,
                }

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
                    except Exception as exc:  # noqa: BLE001
                        logger.error("Stream failed mid-flight: %s", exc)
                        yield StreamChunk(
                            id="err",
                            model=selected_model,
                            finish_reason="error",
                            content="",
                            is_error=True,
                        )
                    finally:
                        if final_usage is not None:
                            TOKENS.labels(provider, "prompt", selected_key_ref or "anonymous").inc(
                                final_usage.prompt_tokens
                            )
                            TOKENS.labels(
                                provider, "completion", selected_key_ref or "anonymous"
                            ).inc(final_usage.completion_tokens)
                            await self.usage.record(
                                team=selected_team,
                                provider=provider,
                                key_ref=selected_key_ref,
                                model=selected_model,
                                prompt_tokens=final_usage.prompt_tokens,
                                completion_tokens=final_usage.completion_tokens,
                            )

                return StreamingRoutingResult(
                    with_first(),
                    candidate.provider,
                    attempts,
                    attempt_records=attempt_records,
                )
            except Exception as exc:  # noqa: BLE001 - adapters may raise vendor SDK exceptions
                elapsed_ms = int((time.monotonic() - started) * 1000)
                status_code = getattr(exc, "status_code", None)
                if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
                    reason_code = "timeout"
                    status_code = status_code or 408
                elif status_code == 429:
                    reason_code = "rate_limited"
                elif status_code and status_code in (400, 422):
                    reason_code = "bad_request"
                elif status_code and status_code >= 500:
                    reason_code = "server_error"
                else:
                    reason_code = "server_error"

                attempt_records.append(
                    {
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "key_hint": key_hint,
                        "outcome": "failed",
                        "status_code": status_code or 500,
                        "latency_ms": elapsed_ms,
                        "reason_code": reason_code,
                    }
                )
                self.last_attempts = list(attempt_records)

                # Client 400 check before first byte: NO FALLBACK!
                if reason_code == "bad_request" or status_code in (400, 422):
                    if not isinstance(exc, ProviderError):
                        err = ProviderError(str(exc), status_code=400, retryable=False)
                    else:
                        err = exc
                    err.attempt_records = attempt_records  # type: ignore[attr-defined]
                    err.attempts = attempts  # type: ignore[attr-defined]
                    raise err

                await self.circuits.failure(identity)
                if reason_code == "rate_limited":
                    await self.key_pool.set_cooldown(key_ref, 30.0)
                elif reason_code == "auth_failure":
                    await self.key_pool.disable(key_ref)
                FAILOVERS.labels(candidate.provider, type(exc).__name__).inc()
        raise NoProviderAvailable(
            f"all streaming providers failed for '{request.model}' (tried: {', '.join(attempts) or 'none'})"
        )
