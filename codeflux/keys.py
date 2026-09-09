from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from codeflux.storage import CredentialVault


@dataclass
class KeyState:
    reference: str
    last_used: float = 0.0
    remaining_requests: int | None = None
    reset_at: float = 0.0


class KeyPool:
    """Concurrency-safe LRU selector with basic rate-limit awareness."""

    def __init__(self, vault: CredentialVault):
        self.vault = vault
        self._states: dict[str, KeyState] = {}
        self._lock = asyncio.Lock()

    async def select(self, provider: str, preferred_ref: str | None = None) -> tuple[str | None, str | None]:
        # A configured reference is the preferred seed key, not an instruction to
        # ignore keys later contributed to the provider's shared pool.
        references = await self.vault.references(provider)
        if preferred_ref and preferred_ref in references:
            references.remove(preferred_ref)
            references.insert(0, preferred_ref)
        references = [ref for ref in references if ref]
        if not references:
            return None, None
        now = time.monotonic()
        async with self._lock:
            states = [self._states.setdefault(ref, KeyState(ref)) for ref in references]
            eligible = [s for s in states if s.remaining_requests != 0 or s.reset_at <= now]
            while eligible:
                state = min(eligible, key=lambda item: item.last_used)
                eligible.remove(state)
                key = await self.vault.get(state.reference)
                if key:
                    state.last_used = now
                    return state.reference, key
        return None, None

    def snapshot(self) -> list[dict[str, int | float | str | None]]:
        return [
            {
                "reference": state.reference,
                "remaining_requests": state.remaining_requests,
                "reset_in_seconds": max(0.0, state.reset_at - time.monotonic()) if state.reset_at else None,
            }
            for state in self._states.values()
        ]

    async def update_limits(self, reference: str | None, headers: dict[str, str]) -> None:
        if not reference:
            return
        remaining = headers.get("x-ratelimit-remaining-requests")
        reset = headers.get("x-ratelimit-reset-requests")
        async with self._lock:
            state = self._states.setdefault(reference, KeyState(reference))
            if remaining and remaining.isdigit():
                state.remaining_requests = int(remaining)
            if reset:
                try:
                    state.reset_at = time.monotonic() + float(reset.rstrip("s"))
                except ValueError:
                    pass
