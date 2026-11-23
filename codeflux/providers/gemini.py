from __future__ import annotations

import json
import time
import uuid
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
        tool_names: dict[str, str] = {}
        for message in request.messages:
            target = system if message.role == "system" else contents
            parts = []
            if message.content:
                parts.append({"text": str(message.content)})
            if message.role == "assistant" and message.tool_calls:
                for tool_call in message.tool_calls:
                    function = tool_call.get("function", {})
                    tool_names[str(tool_call.get("id", ""))] = str(function.get("name", ""))
                    try:
                        arguments = json.loads(function.get("arguments", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        arguments = {"raw_arguments": function.get("arguments", "")}
                    part = {"functionCall": {"name": function.get("name"), "args": arguments}}
                    thought_signature = (
                        tool_call.get("extra_content", {})
                        .get("google", {})
                        .get("thought_signature")
                    )
                    if thought_signature:
                        part["thoughtSignature"] = thought_signature
                    parts.append(part)
            elif message.role == "tool":
                try:
                    response = json.loads(str(message.content or "{}"))
                except json.JSONDecodeError:
                    response = {"result": message.content}
                parts.append(
                    {
                        "functionResponse": {
                            "name": message.name
                            or tool_names.get(message.tool_call_id or "", "tool"),
                            "response": response
                            if isinstance(response, dict)
                            else {"result": response},
                        }
                    }
                )
            if parts:
                target.append(
                    {"role": "model" if message.role == "assistant" else "user", "parts": parts}
                )
        body: dict = {"contents": contents}
        if system:
            body["systemInstruction"] = {
                "parts": [part for item in system for part in item["parts"]]
            }
        generation = {
            "temperature": request.temperature,
            "topP": request.top_p,
            "maxOutputTokens": request.max_tokens,
        }
        body["generationConfig"] = {
            key: value for key, value in generation.items() if value is not None
        }
        if request.tools:
            declarations = []
            for tool in request.tools:
                function = tool.get("function", {})
                declarations.append(
                    {
                        key: value
                        for key, value in {
                            "name": function.get("name"),
                            "description": function.get("description"),
                            "parameters": function.get("parameters"),
                        }.items()
                        if value is not None
                    }
                )
            body["tools"] = [{"functionDeclarations": declarations}]
            if isinstance(request.tool_choice, str) and request.tool_choice in {"none", "required"}:
                body["toolConfig"] = {
                    "functionCallingConfig": {
                        "mode": "NONE" if request.tool_choice == "none" else "ANY"
                    }
                }
            elif isinstance(request.tool_choice, dict):
                function_name = request.tool_choice.get("function", {}).get("name")
                if function_name:
                    body["toolConfig"] = {
                        "functionCallingConfig": {
                            "mode": "ANY",
                            "allowedFunctionNames": [function_name],
                        }
                    }
        return body

    async def chat_completion(
        self, request: NormalizedRequest, api_key: str | None = None
    ) -> NormalizedResponse:
        url = f"{self.base_url}/models/{request.model}:generateContent"
        headers = {"x-goog-api-key": api_key} if api_key else None
        response = await self.client.post(url, json=self._body(request), headers=headers)
        if response.is_error:
            raise ProviderError(
                f"gemini returned {response.status_code}: {response.text[:500]}",
                status_code=response.status_code,
            )
        data = response.json()
        candidate = data.get("candidates", [{}])[0]
        parts = candidate.get("content", {}).get("parts", [])
        content = "".join(part.get("text", "") for part in parts) or None
        tool_calls = []
        for part in parts:
            if "functionCall" not in part:
                continue
            tool_call = {
                "id": f"call_{uuid.uuid4().hex}",
                "type": "function",
                "function": {
                    "name": part["functionCall"].get("name", ""),
                    "arguments": json.dumps(
                        part["functionCall"].get("args", {}), separators=(",", ":")
                    ),
                },
            }
            if part.get("thoughtSignature"):
                tool_call["extra_content"] = {
                    "google": {"thought_signature": part["thoughtSignature"]}
                }
            tool_calls.append(tool_call)
        metadata = data.get("usageMetadata", {})
        usage = Usage(
            prompt_tokens=metadata.get("promptTokenCount", 0),
            completion_tokens=metadata.get("candidatesTokenCount", 0),
            total_tokens=metadata.get("totalTokenCount", 0),
        )
        limit_headers = {
            key.lower(): value
            for key, value in response.headers.items()
            if key.lower().startswith("x-ratelimit-")
        }
        finish_reason = (
            "tool_calls" if tool_calls else candidate.get("finishReason", "STOP").lower()
        )
        return NormalizedResponse(
            model=request.model,
            content=content,
            tool_calls=tool_calls or None,
            finish_reason=finish_reason,
            usage=usage,
            raw=data,
            rate_limit_headers=limit_headers,
        )

    async def stream_chat_completion(
        self, request: NormalizedRequest, api_key: str | None = None
    ) -> AsyncIterator[StreamChunk]:
        url = f"{self.base_url}/models/{request.model}:streamGenerateContent?alt=sse"
        headers = {"x-goog-api-key": api_key} if api_key else None
        chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
        async with self.client.stream(
            "POST", url, json=self._body(request), headers=headers
        ) as response:
            if response.is_error:
                await response.aread()
                raise ProviderError(
                    f"gemini returned {response.status_code}",
                    status_code=response.status_code,
                )
            async for line in response.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                data = json.loads(line[6:])
                candidates = data.get("candidates") or []
                candidate = candidates[0] if candidates else {}
                parts = candidate.get("content", {}).get("parts", [])
                text = "".join(part.get("text", "") for part in parts) or None
                metadata = data.get("usageMetadata", {})
                usage = (
                    Usage(
                        prompt_tokens=metadata.get("promptTokenCount", 0),
                        completion_tokens=metadata.get("candidatesTokenCount", 0),
                        total_tokens=metadata.get("totalTokenCount", 0),
                    )
                    if metadata
                    else None
                )
                yield StreamChunk(
                    id=chunk_id,
                    model=request.model,
                    content=text,
                    finish_reason=candidate.get("finishReason", "").lower() or None,
                    usage=usage,
                )

    async def health_check(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            response = await self.client.get(f"{self.base_url}/models")
            return ProviderHealth(
                provider=self.name,
                state=HealthState.healthy if response.status_code < 500 else HealthState.degraded,
                latency_ms=(time.monotonic() - started) * 1000,
            )
        except httpx.HTTPError as exc:
            return ProviderHealth(
                provider=self.name, state=HealthState.unavailable, detail=str(exc)
            )
