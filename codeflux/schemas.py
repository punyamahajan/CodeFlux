from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]] | None = None
    name: str | None = None
    tool_call_id: str | None = None


class NormalizedRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[Message] = Field(default_factory=list)
    prompt: str | list[str] | None = None
    input: str | list[str] | list[int] | list[list[int]] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    stop: str | list[str] | None = None
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    response_format: dict[str, Any] | None = None
    operation: Literal["chat", "completion", "embedding"] = "chat"
    client_format: Literal["openai", "gemini"] = "openai"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class NormalizedResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex}")
    model: str
    content: str | None = None
    finish_reason: str | None = "stop"
    usage: Usage = Field(default_factory=Usage)
    embeddings: list[list[float]] | None = None
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)
    created: int = Field(default_factory=lambda: int(time.time()))


class StreamChunk(BaseModel):
    id: str
    model: str
    content: str | None = None
    finish_reason: str | None = None


class HealthState(str, Enum):
    healthy = "healthy"
    degraded = "degraded"
    unavailable = "unavailable"
    unknown = "unknown"


class ProviderHealth(BaseModel):
    provider: str
    state: HealthState
    latency_ms: float | None = None
    detail: str | None = None


class GeminiPart(BaseModel):
    text: str | None = None


class GeminiContent(BaseModel):
    role: str = "user"
    parts: list[GeminiPart]


class GeminiRequest(BaseModel):
    contents: list[GeminiContent]
    systemInstruction: GeminiContent | None = None
    generationConfig: dict[str, Any] | None = None
