import pytest

from codeflux.adapters.registry import AdapterRegistry
from codeflux.circuit import CircuitBreaker
from codeflux.config import AppConfig, CandidateConfig, RouteConfig
from codeflux.errors import ProviderError
from codeflux.router import RoutingEngine
from codeflux.schemas import HealthState, NormalizedRequest, NormalizedResponse, ProviderHealth


class Adapter:
    def __init__(self, name, fails=False): self.name, self.fails = name, fails
    async def chat_completion(self, request, api_key=None):
        if self.fails: raise ProviderError("simulated")
        return NormalizedResponse(model=request.model, content="ok")
    async def health_check(self): return ProviderHealth(provider=self.name, state=HealthState.healthy)
    def supports_model(self, model): return True


class Keys:
    async def select(self, provider, preferred_ref=None): return preferred_ref, "secret"


class Usage:
    async def record(self, **kwargs): pass


@pytest.mark.asyncio
async def test_priority_failover():
    registry = object.__new__(AdapterRegistry)
    registry.adapters = {"bad": Adapter("bad", True), "good": Adapter("good")}
    config = AppConfig(routes={"smart": RouteConfig(candidates=[CandidateConfig(provider="bad", model="a"), CandidateConfig(provider="good", model="b")])})
    router = RoutingEngine(config, registry, Keys(), CircuitBreaker(1, 30), Usage())
    result = await router.route(NormalizedRequest(model="smart", messages=[]), "demo")
    assert result.response.content == "ok"
    assert result.provider == "good"
    assert result.attempts == ["bad", "good"]

