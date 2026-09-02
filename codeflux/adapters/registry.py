from __future__ import annotations

import httpx

from codeflux.adapters.base import ProviderAdapter
from codeflux.adapters.gemini import GeminiAdapter
from codeflux.adapters.openai_compatible import OpenAICompatibleAdapter

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "together": "https://api.together.xyz/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "perplexity": "https://api.perplexity.ai",
    "deepseek": "https://api.deepseek.com/v1",
    "cohere": "https://api.cohere.ai/compatibility/v1",
    "xai": "https://api.x.ai/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "ollama": "http://ollama:11434/v1",
    "azure": "https://example.openai.azure.com/openai/deployments/default",
    "bedrock": "http://localhost:8080/v1",  # use an OpenAI-compatible Bedrock bridge
}


class AdapterRegistry:
    def __init__(self, client: httpx.AsyncClient, base_urls: dict[str, str] | None = None):
        urls = {**DEFAULT_BASE_URLS, **(base_urls or {})}
        self.adapters: dict[str, ProviderAdapter] = {
            name: OpenAICompatibleAdapter(name, url, client) for name, url in urls.items()
        }
        self.adapters["gemini"] = GeminiAdapter(
            (base_urls or {}).get("gemini", "https://generativelanguage.googleapis.com/v1beta"), client
        )

    def get(self, provider: str) -> ProviderAdapter:
        try:
            return self.adapters[provider]
        except KeyError as exc:
            raise ValueError(f"unknown provider adapter: {provider}") from exc

    def register(self, name: str, adapter: ProviderAdapter) -> None:
        self.adapters[name] = adapter

