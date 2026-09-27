from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

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


class OpenAICompatibleAdapter:
    def __init__(self, name: str, base_url: str, client: httpx.AsyncClient):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.client = client

    def supports_model(self, model_name: str) -> bool:
        return bool(model_name)

    def _headers(self, api_key: str | None) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def _payload(self, request: NormalizedRequest) -> tuple[str, dict[str, Any]]:
        fields = request.model_dump(
            include={"model", "temperature", "max_tokens", "top_p", "stop", "tools", "response_format"},
            exclude_none=True,
        )
        if request.operation == "embedding":
            return "/embeddings", {"model": request.model, "input": request.input}
        if request.operation == "completion":
            return "/completions", {**fields, "prompt": request.prompt}
        return "/chat/completions", {
            **fields,
            "messages": [message.model_dump(exclude_none=True) for message in request.messages],
            "stream": request.stream,
        }

    async def chat_completion(
        self, request: NormalizedRequest, api_key: str | None = None
    ) -> NormalizedResponse:
        path, payload = self._payload(request)
        try:
            response = await self.client.post(
                f"{self.base_url}{path}", json=payload, headers=self._headers(api_key)
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} transport failure: {exc}") from exc
        if response.is_error:
            detail = response.text[:500]
            raise ProviderError(
                f"{self.name} returned {response.status_code}: {detail}",
                status_code=response.status_code,
                retryable=response.status_code in {401, 403, 408, 409, 429} or response.status_code >= 500,
            )
        data = response.json()
        usage_data = data.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )
        limit_headers = {
            key.lower(): value
            for key, value in response.headers.items()
            if key.lower().startswith("x-ratelimit-")
        }
        if request.operation == "embedding":
            return NormalizedResponse(
                id=data.get("id", f"embd-{uuid.uuid4().hex}"), model=data.get("model", request.model),
                embeddings=[item["embedding"] for item in data.get("data", [])], usage=usage, raw=data,
                rate_limit_headers=limit_headers,
            )
        choice = data.get("choices", [{}])[0]
        content = choice.get("text") if request.operation == "completion" else choice.get("message", {}).get("content")
        return NormalizedResponse(
            id=data.get("id", f"chatcmpl-{uuid.uuid4().hex}"), model=data.get("model", request.model),
            content=content or "", finish_reason=choice.get("finish_reason", "stop"), usage=usage, raw=data,
            created=data.get("created", int(time.time())), rate_limit_headers=limit_headers,
        )

    async def stream_chat_completion(
        self, request: NormalizedRequest, api_key: str | None = None
    ) -> AsyncIterator[StreamChunk]:
        path, payload = self._payload(request)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        async with self.client.stream(
            "POST", f"{self.base_url}{path}", json=payload, headers=self._headers(api_key)
        ) as response:
            if response.is_error:
                await response.aread()
                raise ProviderError(f"{self.name} returned {response.status_code}", status_code=response.status_code)
            async for line in response.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                data = json.loads(line[6:])
                choice = data.get("choices", [{}])[0]
                usage_data = data.get("usage")
                yield StreamChunk(
                    id=data.get("id", ""), model=data.get("model", request.model),
                    content=choice.get("delta", {}).get("content") or choice.get("text"),
                    finish_reason=choice.get("finish_reason"),
                    usage=Usage(
                        prompt_tokens=usage_data.get("prompt_tokens", 0),
                        completion_tokens=usage_data.get("completion_tokens", 0),
                        total_tokens=usage_data.get("total_tokens", 0),
                    ) if usage_data else None,
                )

    async def health_check(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            response = await self.client.get(f"{self.base_url}/models")
            state = HealthState.healthy if response.status_code < 500 else HealthState.degraded
            return ProviderHealth(provider=self.name, state=state, latency_ms=(time.monotonic() - started) * 1000)
        except httpx.HTTPError as exc:
            return ProviderHealth(provider=self.name, state=HealthState.unavailable, detail=str(exc))
