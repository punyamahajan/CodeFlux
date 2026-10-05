from codeflux.normalization import gemini_request, openai_request, to_gemini, to_openai
from codeflux.schemas import GeminiContent, GeminiPart, GeminiRequest, NormalizedResponse, Usage


def test_openai_round_trip():
    request = openai_request({"model": "fast", "messages": [{"role": "user", "content": "hello"}]}, "chat")
    assert request.messages[0].content == "hello"
    result = to_openai(NormalizedResponse(model="native", content="hi", usage=Usage(total_tokens=2)), "chat", "fast")
    assert result["model"] == "fast"
    assert result["choices"][0]["message"]["content"] == "hi"


def test_openai_tool_calls_round_trip():
    tool_calls = [{
        "id": "call_1",
        "type": "function",
        "function": {"name": "write_file", "arguments": '{"path":"app.py"}'},
    }]
    request = openai_request({
        "model": "fast",
        "messages": [{"role": "assistant", "content": None, "tool_calls": tool_calls}],
        "tools": [{"type": "function", "function": {"name": "write_file"}}],
        "tool_choice": "auto",
    }, "chat")
    assert request.messages[0].tool_calls == tool_calls
    assert request.tool_choice == "auto"
    result = to_openai(
        NormalizedResponse(model="native", content=None, tool_calls=tool_calls, finish_reason="tool_calls"),
        "chat",
        "fast",
    )
    assert result["choices"][0]["message"]["tool_calls"] == tool_calls
    assert result["choices"][0]["finish_reason"] == "tool_calls"


def test_gemini_round_trip():
    payload = GeminiRequest(contents=[GeminiContent(parts=[GeminiPart(text="hello")])])
    request = gemini_request("gemini-tier", payload)
    assert request.messages[0].content == "hello"
    result = to_gemini(NormalizedResponse(model="gemini", content="hi"))
    assert result["candidates"][0]["content"]["parts"][0]["text"] == "hi"
