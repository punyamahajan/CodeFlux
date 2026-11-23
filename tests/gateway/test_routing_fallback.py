from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from codeflux.app import create_app
from codeflux.errors import ProviderError
from codeflux.gateway.circuit import CircuitBreaker, CircuitState
from codeflux.gateway.keypool import KeyPool
from codeflux.gateway.router import RoutingEngine
from codeflux.providers.registry import AdapterRegistry
from codeflux.schemas import (
    HealthState,
    NormalizedRequest,
    NormalizedResponse,
    ProviderHealth,
    StreamChunk,
    Usage,
)
from codeflux.settings import AppConfig, CandidateConfig, RouteConfig, Settings


class MockAdapter:
    def __init__(
        self,
        name: str,
        *,
        error: Exception | None = None,
        fail_stream_at_chunk: int | None = None,
    ):
        self.name = name
        self.error = error
        self.fail_stream_at_chunk = fail_stream_at_chunk
        self.call_count = 0

    async def chat_completion(
        self, request: NormalizedRequest, api_key: str | None = None
    ) -> NormalizedResponse:
        self.call_count += 1
        if self.error:
            raise self.error
        return NormalizedResponse(
            model=request.model,
            content=f"reply from {self.name}",
            usage=Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )

    async def stream_chat_completion(
        self, request: NormalizedRequest, api_key: str | None = None
    ) -> AsyncIterator[StreamChunk]:
        self.call_count += 1
        if self.error:
            raise self.error

        for i in range(1, 4):
            if self.fail_stream_at_chunk == i:
                raise ProviderError(f"{self.name} connection dropped mid-stream", status_code=500)
            yield StreamChunk(
                id=f"{self.name}-{i}",
                model=request.model,
                content=f"chunk{i} ",
                finish_reason="stop" if i == 3 else None,
            )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, state=HealthState.healthy)

    def supports_model(self, model: str) -> bool:
        return True


class DummyVault:
    def __init__(self, keys_by_provider: dict[str, list[str]] | None = None):
        self.keys = keys_by_provider or {}

    async def references(self, provider: str) -> list[str]:
        return list(self.keys.get(provider, [f"{provider}_key"]))

    async def get(self, reference: str) -> str | None:
        return f"secret_for_{reference}"


class DummyUsage:
    def __init__(self):
        self.records = []

    async def record(self, **kwargs):
        self.records.append(kwargs)


def make_router(
    routes: dict[str, RouteConfig],
    adapters: dict[str, MockAdapter],
    keys_by_provider: dict[str, list[str]] | None = None,
    circuit_breaker: CircuitBreaker | None = None,
) -> tuple[RoutingEngine, CircuitBreaker, KeyPool]:
    registry = object.__new__(AdapterRegistry)
    registry.adapters = adapters
    vault = DummyVault(keys_by_provider)
    key_pool = KeyPool(vault)
    circuits = circuit_breaker or CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)
    config = AppConfig(default_route=next(iter(routes.keys())), routes=routes)
    router = RoutingEngine(config, registry, key_pool, circuits, DummyUsage())
    return router, circuits, key_pool


@pytest.mark.asyncio
async def test_fallback_on_429():
    adapters = {
        "primary": MockAdapter(
            "primary", error=ProviderError("Rate limit exceeded", status_code=429)
        ),
        "secondary": MockAdapter("secondary"),
    }
    routes = {
        "smart": RouteConfig(
            candidates=[
                CandidateConfig(provider="primary", model="model-a"),
                CandidateConfig(provider="secondary", model="model-b"),
            ]
        )
    }
    router, _circuits, _key_pool = make_router(routes, adapters)
    req = NormalizedRequest(model="smart", messages=[])

    result = await router.route(req, team="test-team")

    assert result.provider == "secondary"
    assert result.attempts == ["primary", "secondary"]
    assert len(result.attempt_records) == 2

    # Verify attempt records details
    att0 = result.attempt_records[0]
    assert att0["provider"] == "primary"
    assert att0["outcome"] == "failed"
    assert att0["status_code"] == 429
    assert att0["reason_code"] == "rate_limited"

    att1 = result.attempt_records[1]
    assert att1["provider"] == "secondary"
    assert att1["outcome"] == "succeeded"
    assert att1["status_code"] == 200
    assert att1["reason_code"] == "ok"


@pytest.mark.asyncio
async def test_fallback_on_timeout():
    adapters = {
        "primary": MockAdapter("primary", error=TimeoutError()),
        "secondary": MockAdapter("secondary"),
    }
    routes = {
        "smart": RouteConfig(
            candidates=[
                CandidateConfig(provider="primary", model="model-a", timeout_seconds=1.0),
                CandidateConfig(provider="secondary", model="model-b", timeout_seconds=5.0),
            ]
        )
    }
    router, _circuits, _key_pool = make_router(routes, adapters)
    req = NormalizedRequest(model="smart", messages=[])

    result = await router.route(req, team="test-team")

    assert result.provider == "secondary"
    assert result.attempts == ["primary", "secondary"]
    assert result.attempt_records[0]["outcome"] == "failed"
    assert result.attempt_records[0]["reason_code"] == "timeout"
    assert result.attempt_records[0]["status_code"] == 408
    assert result.attempt_records[1]["outcome"] == "succeeded"
    assert result.attempt_records[1]["reason_code"] == "ok"


@pytest.mark.asyncio
async def test_fallback_on_5xx():
    adapters = {
        "primary": MockAdapter("primary", error=ProviderError("Bad Gateway", status_code=502)),
        "secondary": MockAdapter("secondary"),
    }
    routes = {
        "smart": RouteConfig(
            candidates=[
                CandidateConfig(provider="primary", model="model-a"),
                CandidateConfig(provider="secondary", model="model-b"),
            ]
        )
    }
    router, _circuits, _key_pool = make_router(routes, adapters)
    req = NormalizedRequest(model="smart", messages=[])

    result = await router.route(req, team="test-team")

    assert result.provider == "secondary"
    assert result.attempts == ["primary", "secondary"]
    assert result.attempt_records[0]["outcome"] == "failed"
    assert result.attempt_records[0]["reason_code"] == "server_error"
    assert result.attempt_records[0]["status_code"] == 502
    assert result.attempt_records[1]["outcome"] == "succeeded"


@pytest.mark.asyncio
async def test_no_fallback_on_400():
    primary_adapter = MockAdapter(
        "primary",
        error=ProviderError("Invalid prompt parameter", status_code=400, retryable=False),
    )
    secondary_adapter = MockAdapter("secondary")
    adapters = {"primary": primary_adapter, "secondary": secondary_adapter}
    routes = {
        "smart": RouteConfig(
            candidates=[
                CandidateConfig(provider="primary", model="model-a"),
                CandidateConfig(provider="secondary", model="model-b"),
            ]
        )
    }
    router, _circuits, _key_pool = make_router(routes, adapters)
    req = NormalizedRequest(model="smart", messages=[])

    with pytest.raises(ProviderError) as exc_info:
        await router.route(req, team="test-team")

    assert exc_info.value.status_code == 400
    # Secondary was NEVER called
    assert secondary_adapter.call_count == 0
    assert primary_adapter.call_count == 1
    # Exactly one attempt recorded
    assert len(router.last_attempts) == 1
    assert router.last_attempts[0]["provider"] == "primary"
    assert router.last_attempts[0]["outcome"] == "failed"
    assert router.last_attempts[0]["status_code"] == 400
    assert router.last_attempts[0]["reason_code"] == "bad_request"


@pytest.mark.asyncio
async def test_breaker_opens_then_recovers(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("codeflux.gateway.circuit.time.monotonic", lambda: clock[0])

    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=10.0, probe_timeout_seconds=30.0)
    identity = "primary:key_1"

    # Initially closed
    assert await breaker.allow(identity)

    # 2 failures trip breaker
    await breaker.failure(identity)
    assert breaker.snapshot()[identity] == CircuitState.closed.value
    await breaker.failure(identity)
    assert breaker.snapshot()[identity] == CircuitState.open.value

    # Call during cooldown is rejected
    clock[0] += 5.0
    assert not await breaker.allow(identity)
    assert breaker.snapshot()[identity] == CircuitState.open.value

    # Cooldown expires -> transitions to half_open on allow
    clock[0] += 6.0  # total 11s elapsed > 10s cooldown
    assert await breaker.allow(identity)
    assert breaker.snapshot()[identity] == CircuitState.half_open.value

    # Successful probe closes the breaker
    await breaker.success(identity)
    assert breaker.snapshot()[identity] == CircuitState.closed.value
    assert await breaker.allow(identity)


@pytest.mark.asyncio
async def test_abandoned_probe_releases_after_expiry(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("codeflux.gateway.circuit.time.monotonic", lambda: clock[0])

    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=5.0, probe_timeout_seconds=30.0)
    identity = "primary:key_1"

    # Trip breaker
    assert await breaker.allow(identity)
    await breaker.failure(identity)
    assert breaker.snapshot()[identity] == CircuitState.open.value

    # Advance clock past cooldown -> allow first probe
    clock[0] += 6.0
    assert await breaker.allow(identity)
    assert breaker.snapshot()[identity] == CircuitState.half_open.value

    # Second probe arrives immediately while first probe is in flight -> rejected
    clock[0] += 2.0
    assert not await breaker.allow(identity)

    # First probe is ABANDONED (neither success nor failure called)
    # Advance clock past probe timeout (30.0s from 106.0 -> 137.0)
    clock[0] += 30.0  # now 138.0 > 136.0 (probe_expires_at)

    # New call arrives -> abandoned probe is released and new probe is allowed!
    assert await breaker.allow(identity)
    assert breaker.snapshot()[identity] == CircuitState.half_open.value


@pytest.mark.asyncio
async def test_task_header_picks_tagged_route():
    adapters = {
        "fast_provider": MockAdapter("fast_provider"),
        "smart_provider": MockAdapter("smart_provider"),
    }
    routes = {
        "smart": RouteConfig(
            task_tag="general",
            candidates=[CandidateConfig(provider="smart_provider", model="smart-m")],
        ),
        "fast": RouteConfig(
            task_tag="code",
            candidates=[CandidateConfig(provider="fast_provider", model="fast-m")],
        ),
    }
    router, _circuits, _key_pool = make_router(routes, adapters)
    req = NormalizedRequest(model="smart", messages=[])

    result = await router.route(req, team="test-team", task_tag="code")

    assert result.provider == "fast_provider"
    assert result.response.model == "fast-m"


@pytest.mark.asyncio
async def test_custom_fallback_header_honored():
    adapters = {
        "p1": MockAdapter("p1", error=ProviderError("unavailable", status_code=503)),
        "p2": MockAdapter("p2"),
        "default_p": MockAdapter("default_p"),
    }
    routes = {
        "smart": RouteConfig(candidates=[CandidateConfig(provider="default_p", model="default-m")])
    }
    router, _circuits, _key_pool = make_router(routes, adapters)
    req = NormalizedRequest(model="smart", messages=[])

    result = await router.route(req, team="test-team", custom_fallback="p1/custom-1,p2/custom-2")

    assert result.provider == "p2"
    assert result.attempts == ["p1", "p2"]
    assert adapters["default_p"].call_count == 0


@pytest.mark.asyncio
async def test_disallowed_model_rejected():
    adapters = {
        "smart_p": MockAdapter("smart_p"),
        "fast_p": MockAdapter("fast_p"),
    }
    routes = {
        "smart": RouteConfig(candidates=[CandidateConfig(provider="smart_p", model="m1")]),
        "fast": RouteConfig(candidates=[CandidateConfig(provider="fast_p", model="m2")]),
    }
    router, _circuits, _key_pool = make_router(routes, adapters)
    req = NormalizedRequest(model="fast", messages=[])

    # Key only allows "smart"
    with pytest.raises(PermissionError) as exc_info:
        await router.route(req, team="test-team", allowed_routes=["smart"])

    assert "not allowed" in str(exc_info.value)
    assert adapters["fast_p"].call_count == 0


@pytest.mark.asyncio
async def test_stream_fallback_only_before_first_byte():
    adapters = {
        "primary": MockAdapter("primary", error=ProviderError("429 rate limit", status_code=429)),
        "secondary": MockAdapter("secondary"),
    }
    routes = {
        "smart": RouteConfig(
            candidates=[
                CandidateConfig(provider="primary", model="model-a"),
                CandidateConfig(provider="secondary", model="model-b"),
            ]
        )
    }
    router, _circuits, _key_pool = make_router(routes, adapters)
    req = NormalizedRequest(model="smart", messages=[], stream=True)

    result = await router.route_stream(req, team="test-team")

    assert result.provider == "secondary"
    assert result.attempts == ["primary", "secondary"]

    chunks = [c async for c in result.chunks]
    assert len(chunks) == 3
    assert chunks[0].content == "chunk1 "


@pytest.mark.asyncio
async def test_stream_midflight_error_emits_clean_sse_error():
    adapters = {
        "primary": MockAdapter("primary", fail_stream_at_chunk=2),
        "secondary": MockAdapter("secondary"),
    }
    routes = {
        "smart": RouteConfig(
            candidates=[
                CandidateConfig(provider="primary", model="model-a"),
                CandidateConfig(provider="secondary", model="model-b"),
            ]
        )
    }
    router, _circuits, _key_pool = make_router(routes, adapters)
    req = NormalizedRequest(model="smart", messages=[], stream=True)

    result = await router.route_stream(req, team="test-team")

    # It chose primary because first chunk succeeded
    assert result.provider == "primary"
    assert result.attempts == ["primary"]

    chunks = [c async for c in result.chunks]
    # Chunk 1 was yielded, chunk 2 failed and resulted in an error chunk
    assert len(chunks) == 2
    assert chunks[0].content == "chunk1 "
    assert chunks[1].finish_reason == "error"
    assert chunks[1].is_error is True

    # Secondary was NEVER called
    assert adapters["secondary"].call_count == 0


def test_demo_outage_endpoint(tmp_path):
    config_path = tmp_path / "routes.yaml"
    config_path.write_text(
        """
routes:
  smart:
    candidates:
      - provider: primary
        model: m1
default_route: smart
"""
    )
    settings = Settings(
        _env_file=None,
        config_path=config_path,
        demo_mode=True,
    )
    app = create_app(settings)

    # Create dummy admin user and mock dependency
    from codeflux.api.deps import require_admin
    from codeflux.db.models import User

    fake_admin = User(id="usr_admin", org_id="org_demo", role="admin", email="admin@test.com")
    app.dependency_overrides[require_admin] = lambda: fake_admin

    with TestClient(app) as client:
        # 1. Toggle outage on for "primary"
        resp = client.post("/api/admin/demo/outage", json={"provider": "primary", "outage": True})
        assert resp.status_code == 200
        assert resp.json() == {"provider": "primary", "outage": True}
        assert "primary" in client.app.state.demo_outages
        assert "primary" in client.app.state.router.demo_outages

        # 2. Toggle outage off
        resp2 = client.post("/api/admin/demo/outage", json={"provider": "primary", "outage": False})
        assert resp2.status_code == 200
        assert resp2.json() == {"provider": "primary", "outage": False}
        assert "primary" not in client.app.state.demo_outages
        assert "primary" not in client.app.state.router.demo_outages


@pytest.mark.asyncio
async def test_demo_outage_routing_causes_429_failover():
    adapters = {
        "primary": MockAdapter("primary"),
        "secondary": MockAdapter("secondary"),
    }
    routes = {
        "smart": RouteConfig(
            candidates=[
                CandidateConfig(provider="primary", model="m1"),
                CandidateConfig(provider="secondary", model="m2"),
            ]
        )
    }
    router, _circuits, key_pool = make_router(routes, adapters)
    # Enable demo outage on primary
    router.demo_outages.add("primary")

    req = NormalizedRequest(model="smart", messages=[])
    result = await router.route(req, team="admin")

    assert result.provider == "secondary"
    assert result.attempts == ["primary", "secondary"]
    assert result.attempt_records[0]["status_code"] == 429
    assert result.attempt_records[0]["reason_code"] == "rate_limited"
    assert result.attempt_records[1]["status_code"] == 200

    # Turn off outage, clear key cooldown, primary succeeds
    router.demo_outages.clear()
    await router.circuits.success("primary:primary_key")
    if "primary_key" in key_pool._states:
        key_pool._states["primary_key"].reset_at = 0.0
    result2 = await router.route(req, team="admin")
    assert result2.provider == "primary"
    assert result2.attempts == ["primary"]


@pytest.mark.asyncio
async def test_strategies_round_robin_and_least_latency():
    adapters = {
        "p1": MockAdapter("p1"),
        "p2": MockAdapter("p2"),
    }
    # Round robin
    rr_routes = {
        "rr": RouteConfig(
            strategy="round-robin",
            candidates=[
                CandidateConfig(provider="p1", model="m1"),
                CandidateConfig(provider="p2", model="m2"),
            ],
        )
    }
    router_rr, _, _ = make_router(rr_routes, adapters)
    req = NormalizedRequest(model="rr", messages=[])

    res1 = await router_rr.route(req, team="demo")
    assert res1.provider == "p1"
    res2 = await router_rr.route(req, team="demo")
    assert res2.provider == "p2"
    res3 = await router_rr.route(req, team="demo")
    assert res3.provider == "p1"

    # Least latency
    ll_routes = {
        "ll": RouteConfig(
            strategy="least-latency",
            candidates=[
                CandidateConfig(provider="p1", model="m1"),
                CandidateConfig(provider="p2", model="m2"),
            ],
        )
    }
    router_ll, _, _ = make_router(ll_routes, adapters)
    # Seed p1 with high latency (500ms) and p2 with low latency (50ms)
    router_ll._latencies["p1"].append(0.500)
    router_ll._latencies["p2"].append(0.050)

    req_ll = NormalizedRequest(model="ll", messages=[])
    res_ll = await router_ll.route(req_ll, team="demo")
    assert res_ll.provider == "p2"  # p2 chosen first due to lower latency
