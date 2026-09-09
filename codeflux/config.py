from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CandidateConfig(BaseModel):
    provider: str
    model: str
    api_key_ref: str | None = None
    weight: float = 1.0
    base_url: str | None = None
    timeout_seconds: float = 30.0


class RouteConfig(BaseModel):
    strategy: Literal["priority", "round-robin", "least-latency", "weighted-random"] = "priority"
    candidates: list[CandidateConfig]
    total_timeout_seconds: float = 60.0
    pii_redaction: bool = False
    allowed_teams: list[str] = Field(default_factory=list)
    ollama_fallback_model: str | None = None
    ollama_fallback_timeout_seconds: float = 120.0


class CircuitConfig(BaseModel):
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0


class AppConfig(BaseModel):
    routes: dict[str, RouteConfig]
    circuit_breaker: CircuitConfig = Field(default_factory=CircuitConfig)
    provider_base_urls: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def routes_have_candidates(self) -> AppConfig:
        if any(not route.candidates for route in self.routes.values()):
            raise ValueError("every route must contain at least one candidate")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CODEFLUX_", env_file=".env", extra="ignore")

    master_secret: str = "development-only-change-me"
    config_path: Path = Path("config/routes.yaml")
    database_url: str = "sqlite+aiosqlite:///./data/codeflux.db"
    gateway_keys: str = "demo-key:demo"
    credentials_json: str = "{}"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    dashboard_password: str = ""
    dashboard_gateway_url: str = "http://localhost:8000"

    def client_keys(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for pair in self.gateway_keys.split(","):
            key, separator, team = pair.strip().partition(":")
            if key:
                result[key] = team if separator else "default"
        return result


def load_config(path: Path | str) -> AppConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        return AppConfig.model_validate(yaml.safe_load(handle))
