from __future__ import annotations

import time
from collections.abc import AsyncIterator

import httpx

from codeflux.errors import ProviderError
from codeflux.schemas import (
    HealthState,
    NormalizedRequest,
    NormalizedResponse,
    ProviderHealth,
    StreamChunk,
    Usage,
)


class GeminiAdapter:
    name = "gemini"

    def __init__(self, base_url: str, client: httpx.AsyncClient):
        self.base_url = base_url.rstrip("/")
        self.client = client

    def supports_model(self, model_name: str) -> bool:
        return model_name.startswith("gemini") or bool(model_name)

    def _body(self, request: NormalizedRequest) -> dict:
        contents = []
        system = []
        for message in request.messages:
            target = system if message.role == "system" else contents
            target.append({"role": "model" if message.role == "assistant" else "user", "parts": [{"text": str(message.content or "")}]})
        body: dict = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [part for item in system for part in item["parts"]]}
        generation = {"temperature": request.temperature, "topP": request.top_p, "maxOutputTokens": request.max_tokens}
        body["generationConfig"] = {key: value for key, value in generation.items() if value is not None}
        return body

    async def chat_completion(self, request: NormalizedRequest, api_key: str | None = None) -> NormalizedResponse:
        url = f"{self.base_url}/models/{request.model}:generateContent"
        response = await self.client.post(url, json=self._body(request), params={"key": api_key} if api_key else None)
        if response.is_error:
            raise ProviderError(f"gemini returned {response.status_code}: {response.text[:500]}", status_code=response.status_code)
        data = response.json()
        candidate = data.get("candidates", [{}])[0]
        content = "".join(part.get("text", "") for part in candidate.get("content", {}).get("parts", []))
        metadata = data.get("usageMetadata", {})
        usage = Usage(prompt_tokens=metadata.get("promptTokenCount", 0), completion_tokens=metadata.get("candidatesTokenCount", 0), total_tokens=metadata.get("totalTokenCount", 0))
        return NormalizedResponse(model=request.model, content=content, finish_reason=candidate.get("finishReason", "STOP").lower(), usage=usage, raw=data)

    async def stream_chat_completion(self, request: NormalizedRequest, api_key: str | None = None) -> AsyncIterator[StreamChunk]:
        # Gemini SSE formats vary; a non-buffering implementation can be added without changing the router contract.
        result = await self.chat_completion(request, api_key)
        yield StreamChunk(id=result.id, model=result.model, content=result.content, finish_reason=result.finish_reason)

    async def health_check(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            response = await self.client.get(f"{self.base_url}/models")
            return ProviderHealth(provider=self.name, state=HealthState.healthy if response.status_code < 500 else HealthState.degraded, latency_ms=(time.monotonic() - started) * 1000)
        except httpx.HTTPError as exc:
            return ProviderHealth(provider=self.name, state=HealthState.unavailable, detail=str(exc))

