from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator
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
    # Used when a client sends a model name that matches no route or candidate.
    default_route: str | None = None
    default_embedding_route: str | None = None

    @model_validator(mode="after")
    def routes_have_candidates(self) -> AppConfig:
        if any(not route.candidates for route in self.routes.values()):
            raise ValueError("every route must contain at least one candidate")
        for name in (self.default_route, self.default_embedding_route):
            if name and name not in self.routes:
                raise ValueError(f"default route '{name}' is not defined in routes")
        return self


_THROWAWAY_MASTER_KEY: str | None = None
_THROWAWAY_JWT_SECRET: str | None = None
_THROWAWAY_KEY_HMAC_SECRET: str | None = None


def _get_throwaway_master_key() -> str:
    global _THROWAWAY_MASTER_KEY
    if not _THROWAWAY_MASTER_KEY:
        from cryptography.fernet import Fernet

        _THROWAWAY_MASTER_KEY = Fernet.generate_key().decode()
    return _THROWAWAY_MASTER_KEY


def _get_throwaway_jwt_secret() -> str:
    global _THROWAWAY_JWT_SECRET
    if not _THROWAWAY_JWT_SECRET:
        import secrets

        _THROWAWAY_JWT_SECRET = secrets.token_urlsafe(32)
    return _THROWAWAY_JWT_SECRET


def _get_throwaway_key_hmac_secret() -> str:
    global _THROWAWAY_KEY_HMAC_SECRET
    if not _THROWAWAY_KEY_HMAC_SECRET:
        import secrets

        _THROWAWAY_KEY_HMAC_SECRET = secrets.token_hex(32)
    return _THROWAWAY_KEY_HMAC_SECRET


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CODEFLUX_", env_file=".env", extra="ignore")

    env: str = Field(default="dev", validation_alias=AliasChoices("ENV", "CODEFLUX_ENV"))
    demo_mode: bool = Field(
        default=False, validation_alias=AliasChoices("DEMO_MODE", "CODEFLUX_DEMO_MODE")
    )
    master_key: str = Field(
        default="", validation_alias=AliasChoices("MASTER_KEY", "CODEFLUX_MASTER_KEY")
    )
    jwt_secret: str = Field(
        default="", validation_alias=AliasChoices("JWT_SECRET", "CODEFLUX_JWT_SECRET")
    )
    key_hmac_secret: str = Field(
        default="", validation_alias=AliasChoices("KEY_HMAC_SECRET", "CODEFLUX_KEY_HMAC_SECRET")
    )
    cors_origins: str = Field(
        default="*", validation_alias=AliasChoices("CORS_ORIGINS", "CODEFLUX_CORS_ORIGINS")
    )
    master_secret: str = Field(
        default="", validation_alias=AliasChoices("MASTER_SECRET", "CODEFLUX_MASTER_SECRET")
    )
    config_path: Path = Path("config/routes.yaml")
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/omnikey",
        validation_alias=AliasChoices("DATABASE_URL", "CODEFLUX_DATABASE_URL"),
    )
    gateway_keys: str = "demo-key:demo"

    @model_validator(mode="after")
    def validate_secrets(self) -> Settings:
        is_test_env = self.env.strip().lower() in ("test", "testing")
        known_defaults = {
            "",
            "change-me",
            "development-only-change-me",
            "default",
            "secret",
            "password",
            "test",
            "jwt-secret",
            "master-key",
            "key-hmac-secret",
            "your-secret-here",
        }

        if is_test_env:
            if not self.master_key or self.master_key.strip().lower() in known_defaults:
                self.master_key = _get_throwaway_master_key()
            if not self.jwt_secret or self.jwt_secret.strip().lower() in known_defaults:
                self.jwt_secret = _get_throwaway_jwt_secret()
            if not self.key_hmac_secret or self.key_hmac_secret.strip().lower() in known_defaults:
                self.key_hmac_secret = _get_throwaway_key_hmac_secret()
        else:
            secrets_to_check = {
                "MASTER_KEY": self.master_key,
                "JWT_SECRET": self.jwt_secret,
                "KEY_HMAC_SECRET": self.key_hmac_secret,
            }
            for name, val in secrets_to_check.items():
                if not val or val.strip().lower() in known_defaults:
                    raise ValueError(
                        f"Secret '{name}' must be set and cannot use a known default outside ENV=test"
                    )

        self.master_secret = self.master_key

        return self

    @field_validator("database_url", mode="after")
    @classmethod
    def normalize_db_url(cls, v: str) -> str:
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        if "sslmode=require" in v:
            v = v.replace("sslmode=require", "ssl=require")
        return v

    credentials_json: str = "{}"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    dashboard_password: str = ""
    dashboard_gateway_url: str = "http://localhost:8000"
    # Address that apps should call; differs from dashboard_gateway_url inside Docker.
    public_url: str = ""

    def client_keys(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for pair in self.gateway_keys.split(","):
            key, separator, team = pair.strip().partition(":")
            if key:
                result[key] = team if separator else "default"
        return result

    def admin_key(self) -> str | None:
        return next((key for key, team in self.client_keys().items() if team == "admin"), None)


def load_config(path: Path | str) -> AppConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        return AppConfig.model_validate(yaml.safe_load(handle))
