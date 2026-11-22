import json

import pytest
from fastapi.testclient import TestClient

from codeflux.app import create_app
from codeflux.errors import NoProviderAvailable
from codeflux.gateway.router import RoutingEngine
from codeflux.schemas import NormalizedResponse, StreamChunk, Usage
from codeflux.settings import AppConfig, CandidateConfig, RouteConfig, Settings

CONFIG = AppConfig(
    default_route="fast",
    routes={
        "smart": RouteConfig(
            candidates=[
                CandidateConfig(provider="openai", model="gpt-4o-mini"),
                CandidateConfig(provider="gemini", model="gemini-2.0-flash"),
            ]
        ),
        "fast": RouteConfig(
            candidates=[CandidateConfig(provider="groq", model="llama-3.3-70b-versatile")]
        ),
        "embeddings": RouteConfig(
            candidates=[CandidateConfig(provider="openai", model="text-embedding-3-small")]
        ),
    },
)


def resolver(config: AppConfig = CONFIG) -> RoutingEngine:
    return RoutingEngine(config, None, None, None, None, redactor=object())


def test_route_alias_is_used_as_is():
    alias, route = resolver().resolve("smart")
    assert alias == "smart"
    assert [c.model for c in route.candidates] == ["gpt-4o-mini", "gemini-2.0-flash"]


def test_provider_model_name_moves_matching_candidate_first():
    alias, route = resolver().resolve("models/gemini-2.0-flash")
    assert alias == "smart"
    assert [c.model for c in route.candidates] == ["gemini-2.0-flash", "gpt-4o-mini"]


def test_unknown_model_uses_default_route():
    assert resolver().resolve("gpt-4")[0] == "fast"
    assert resolver().resolve("whatever", "embedding")[0] == "embeddings"


def test_without_default_first_matching_route_is_used():
    config = CONFIG.model_copy(update={"default_route": None})
    assert resolver(config).resolve("gpt-4")[0] == "smart"
    with pytest.raises(NoProviderAvailable):
        resolver(AppConfig(routes={"fast": CONFIG.routes["fast"]})).resolve("x", "embedding")


class FakeRouter:
    def __init__(self):
        self.requests = []

    async def route(self, request, team):
        self.requests.append((request, team))
        return type(
            "Result",
            (),
            {
                "response": NormalizedResponse(
                    model="native", content="hi", usage=Usage(total_tokens=3)
                ),
                "provider": "fake",
                "attempts": ["fake"],
            },
        )()

    async def route_stream(self, request, team):
        async def chunks():
            yield StreamChunk(id="c1", model="native", content="hi")
            yield StreamChunk(id="c1", model="native", finish_reason="stop")

        return type("Result", (), {"chunks": chunks(), "provider": "fake", "attempts": ["fake"]})()


@pytest.fixture
def client(tmp_path):
    config_path = tmp_path / "routes.yaml"
    config_path.write_text(
        json.dumps({"routes": {"smart": {"candidates": [{"provider": "openai", "model": "m"}]}}})
    )
    settings = Settings(
        _env_file=None,
        config_path=config_path,
        gateway_keys="secret-key:admin",
    )
    with TestClient(create_app(settings)) as test_client:
        test_client.app.state.router = FakeRouter()
        yield test_client


@pytest.mark.parametrize(
    "auth",
    [
        {"headers": {"Authorization": "Bearer secret-key"}},
        {"headers": {"x-api-key": "secret-key"}},
        {"headers": {"x-goog-api-key": "secret-key"}},
        {"params": {"key": "secret-key"}},
    ],
)
def test_key_accepted_in_every_sdk_location(client, auth):
    assert client.get("/v1/me", **auth).json()["team"] == "admin"


def test_errors_use_openai_shape(client):
    body = client.get("/v1/me", headers={"Authorization": "Bearer wrong"}).json()
    assert body["error"]["type"] == "invalid_api_key"
    assert body["error"]["code"] == 401


def test_openai_stream_chunks_include_created(client):
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer secret-key"},
        json={
            "model": "gpt-4o",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")
    ]
    assert events[0]["choices"][0]["delta"]["content"] == "hi"
    assert all(isinstance(event["created"], int) for event in events)


def test_gemini_sdk_style_requests(client):
    payload = {"contents": [{"role": "user", "parts": [{"text": "hello"}]}]}
    headers = {"x-goog-api-key": "secret-key"}
    single = client.post(
        "/v1beta/models/gemini-2.0-flash:generateContent", headers=headers, json=payload
    ).json()
    assert single["candidates"][0]["content"]["parts"][0]["text"] == "hi"
    stream = client.post(
        "/v1beta/models/gemini-2.0-flash:streamGenerateContent?alt=sse",
        headers=headers,
        json=payload,
    )
    events = [
        json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")
    ]
    assert events[0]["candidates"][0]["content"]["parts"][0]["text"] == "hi"
    assert events[-1]["candidates"][0]["finishReason"] == "STOP"
