import json

import httpx
import pytest

from codeflux.adapters.gemini import GeminiAdapter
from codeflux.adapters.openai_compatible import OpenAICompatibleAdapter
from codeflux.schemas import Message, NormalizedRequest

TOOLS = [{
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Write a workspace file",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}]


@pytest.mark.asyncio
async def test_openai_adapter_preserves_tool_calls():
    tool_calls = [{
        "id": "call_1",
        "type": "function",
        "function": {"name": "write_file", "arguments": '{"path":"app.py"}'},
    }]

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["tools"] == TOOLS
        assert payload["tool_choice"] == "auto"
        return httpx.Response(200, json={
            "model": "native",
            "choices": [{"message": {"content": None, "tool_calls": tool_calls}, "finish_reason": "tool_calls"}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAICompatibleAdapter("test", "https://provider.test/v1", client)
        result = await adapter.chat_completion(NormalizedRequest(
            model="native",
            messages=[Message(role="user", content="Edit app.py")],
            tools=TOOLS,
            tool_choice="auto",
        ), "secret")
    assert result.content is None
    assert result.tool_calls == tool_calls
    assert result.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_gemini_adapter_translates_function_calls():
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        declaration = payload["tools"][0]["functionDeclarations"][0]
        assert declaration["name"] == "write_file"
        assert request.headers["x-goog-api-key"] == "secret"
        assert "key=" not in str(request.url)
        return httpx.Response(200, json={
            "candidates": [{
                "content": {"parts": [{
                    "functionCall": {"name": "write_file", "args": {"path": "app.py"}},
                    "thoughtSignature": "signed-thought",
                }]},
                "finishReason": "STOP",
            }]
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = GeminiAdapter("https://gemini.test/v1beta", client)
        result = await adapter.chat_completion(NormalizedRequest(
            model="gemini-test",
            messages=[Message(role="user", content="Edit app.py")],
            tools=TOOLS,
        ), "secret")
    assert result.content is None
    assert result.tool_calls[0]["function"]["name"] == "write_file"
    assert result.tool_calls[0]["extra_content"]["google"]["thought_signature"] == "signed-thought"
    assert result.finish_reason == "tool_calls"

    follow_up = NormalizedRequest(
        model="gemini-test",
        messages=[Message(role="assistant", content=None, tool_calls=result.tool_calls)],
    )
    assert adapter._body(follow_up)["contents"][0]["parts"][0]["thoughtSignature"] == "signed-thought"
