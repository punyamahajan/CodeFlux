from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum


class CircuitState(str, Enum):
    closed = "closed"
    open = "open"
    half_open = "half_open"


@dataclass
class Circuit:
    failures: int = 0
    state: CircuitState = CircuitState.closed
    opened_at: float = 0.0
    probe_in_flight: bool = False


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 30.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._circuits: dict[str, Circuit] = {}
        self._lock = asyncio.Lock()

    async def allow(self, identity: str) -> bool:
        async with self._lock:
            circuit = self._circuits.setdefault(identity, Circuit())
            if circuit.state == CircuitState.closed:
                return True
            if circuit.state == CircuitState.open and time.monotonic() - circuit.opened_at >= self.cooldown_seconds:
                circuit.state = CircuitState.half_open
            if circuit.state == CircuitState.half_open and not circuit.probe_in_flight:
                circuit.probe_in_flight = True
                return True
            return False

    async def success(self, identity: str) -> None:
        async with self._lock:
            self._circuits[identity] = Circuit()

    async def failure(self, identity: str) -> None:
        async with self._lock:
            circuit = self._circuits.setdefault(identity, Circuit())
            circuit.failures += 1
            circuit.probe_in_flight = False
            if circuit.state == CircuitState.half_open or circuit.failures >= self.failure_threshold:
                circuit.state = CircuitState.open
                circuit.opened_at = time.monotonic()

    def snapshot(self) -> dict[str, str]:
        return {identity: circuit.state.value for identity, circuit in self._circuits.items()}
