import pytest

from codeflux.circuit import CircuitBreaker, CircuitState


@pytest.mark.asyncio
async def test_circuit_transitions(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("codeflux.circuit.time.monotonic", lambda: clock[0])
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=5)
    assert await breaker.allow("p:k")
    await breaker.failure("p:k")
    await breaker.failure("p:k")
    assert breaker.snapshot()["p:k"] == CircuitState.open
    assert not await breaker.allow("p:k")
    clock[0] += 6
    assert await breaker.allow("p:k")
    assert breaker.snapshot()["p:k"] == CircuitState.half_open
    await breaker.success("p:k")
    assert breaker.snapshot()["p:k"] == CircuitState.closed

