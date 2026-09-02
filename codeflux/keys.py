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
        references = [preferred_ref] if preferred_ref else await self.vault.references(provider)
        references = [ref for ref in references if ref]
        if not references:
            return None, None
        now = time.monotonic()
        async with self._lock:
            states = [self._states.setdefault(ref, KeyState(ref)) for ref in references]
            eligible = [s for s in states if s.remaining_requests != 0 or s.reset_at <= now]
            if not eligible:
                return None, None
            state = min(eligible, key=lambda item: item.last_used)
            state.last_used = now
        return state.reference, await self.vault.get(state.reference)

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

