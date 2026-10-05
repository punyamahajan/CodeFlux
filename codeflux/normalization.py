from __future__ import annotations

from typing import Any

from codeflux.schemas import GeminiRequest, Message, NormalizedRequest, NormalizedResponse


def openai_request(payload: dict[str, Any], operation: str) -> NormalizedRequest:
    data = dict(payload)
    data["operation"] = operation
    data["client_format"] = "openai"
    return NormalizedRequest.model_validate(data)


def gemini_request(model: str, payload: GeminiRequest) -> NormalizedRequest:
    messages: list[Message] = []
    if payload.systemInstruction:
        messages.append(Message(role="system", content="".join(part.text or "" for part in payload.systemInstruction.parts)))
    for content in payload.contents:
        role = "assistant" if content.role == "model" else "user"
        messages.append(Message(role=role, content="".join(part.text or "" for part in content.parts)))
    generation = payload.generationConfig or {}
    return NormalizedRequest(model=model, messages=messages, temperature=generation.get("temperature"), max_tokens=generation.get("maxOutputTokens"), top_p=generation.get("topP"), client_format="gemini")


def to_openai(response: NormalizedResponse, operation: str, logical_model: str) -> dict[str, Any]:
    if operation == "embedding":
        return {"object": "list", "data": [{"object": "embedding", "index": i, "embedding": vector} for i, vector in enumerate(response.embeddings or [])], "model": logical_model, "usage": response.usage.model_dump()}
    choice = {"index": 0, "finish_reason": response.finish_reason}
    if operation == "completion":
        choice["text"] = response.content
    else:
        choice["message"] = {"role": "assistant", "content": response.content}
        if response.tool_calls:
            choice["message"]["tool_calls"] = response.tool_calls
    return {"id": response.id, "object": "text_completion" if operation == "completion" else "chat.completion", "created": response.created, "model": logical_model, "choices": [choice], "usage": response.usage.model_dump()}


def to_gemini(response: NormalizedResponse) -> dict[str, Any]:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": response.content or ""}]}, "finishReason": (response.finish_reason or "stop").upper(), "index": 0}], "usageMetadata": {"promptTokenCount": response.usage.prompt_tokens, "candidatesTokenCount": response.usage.completion_tokens, "totalTokenCount": response.usage.total_tokens}}
