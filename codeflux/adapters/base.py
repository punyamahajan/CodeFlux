from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from codeflux.schemas import NormalizedRequest, NormalizedResponse, ProviderHealth, StreamChunk


class ProviderAdapter(Protocol):
    name: str

    async def chat_completion(
        self, request: NormalizedRequest, api_key: str | None = None
    ) -> NormalizedResponse: ...

    async def stream_chat_completion(
        self, request: NormalizedRequest, api_key: str | None = None
    ) -> AsyncIterator[StreamChunk]: ...

    async def health_check(self) -> ProviderHealth: ...

    def supports_model(self, model_name: str) -> bool: ...

