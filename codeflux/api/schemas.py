from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class PaginatedResponse[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


def encode_cursor(created_at: datetime, item_id: str) -> str:
    """Encode created_at timestamp and item_id into an opaque URL-safe base64 cursor."""
    iso_time = created_at.astimezone(UTC).isoformat()
    raw = f"{iso_time}|{item_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("utf-8")


def decode_cursor(cursor: str) -> tuple[datetime, str] | None:
    """Decode an opaque cursor into (created_at, item_id). Returns None on error."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        iso_time, _, item_id = raw.partition("|")
        created_at = datetime.fromisoformat(iso_time)
        return created_at, item_id
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None


# ============================================================================
# Auth Schemas
# ============================================================================


class AdminSignupRequest(BaseModel):
    org_name: str = Field(min_length=1, max_length=128)
    email: EmailStr
    password: str = Field(min_length=8)


class MemberSignupRequest(BaseModel):
    invite_code: str = Field(min_length=1)  # org_id
    email: EmailStr
    password: str = Field(min_length=8)


class SignupRequest(BaseModel):
    """Unified signup request supporting admin org creation or member invite join."""

    email: EmailStr
    password: str = Field(min_length=8)
    org_name: str | None = None
    invite_code: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    org_id: str | None = None


class UserResponse(BaseModel):
    id: str
    org_id: str
    email: str
    role: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuthResponse(BaseModel):
    token: str
    user: UserResponse


class MeResponse(BaseModel):
    id: str
    org_id: str
    email: str
    role: str
    org_name: str
    created_at: datetime


# ============================================================================
# Vault Schemas
# ============================================================================


class VaultAddRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    api_key: str = Field(min_length=1)


class VaultCredentialResponse(BaseModel):
    id: str
    provider: str
    key_hint: str
    enabled: bool
    created_at: datetime
    last_used_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class VaultPatchRequest(BaseModel):
    enabled: bool


# ============================================================================
# Platform Keys Schemas
# ============================================================================


class PlatformKeyCreateRequest(BaseModel):
    user_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=128)
    credit_limit_micro: int = Field(ge=0)
    rpm_limit: int = Field(default=60, ge=1)
    allowed_routes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class PlatformKeyResponse(BaseModel):
    id: str
    user_id: str
    name: str
    key_prefix: str
    credit_limit_micro: int
    credit_remaining_micro: int
    rpm_limit: int
    allowed_routes: list[str]
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    last_used_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class PlatformKeyCreatedResponse(PlatformKeyResponse):
    key: str  # Plaintext key returned strictly once at creation!


class PlatformKeyPatchRequest(BaseModel):
    name: str | None = None
    credit_limit_micro: int | None = Field(default=None, ge=0)
    rpm_limit: int | None = Field(default=None, ge=1)
    allowed_routes: list[str] | None = None
    expires_at: datetime | None = None


# ============================================================================
# Routes Schemas
# ============================================================================


class RouteCandidateSchema(BaseModel):
    provider: str
    model: str
    api_key_ref: str | None = None
    weight: float = 1.0
    base_url: str | None = None
    timeout_seconds: float = 30.0


class RouteCreateRequest(BaseModel):
    alias: str = Field(min_length=1, max_length=128)
    strategy: str = Field(default="priority")
    task_tag: str | None = None
    candidates: list[RouteCandidateSchema] = Field(min_length=1)


class RouteUpdateRequest(BaseModel):
    alias: str | None = None
    strategy: str | None = None
    task_tag: str | None = None
    candidates: list[RouteCandidateSchema] | None = None


class RouteResponse(BaseModel):
    id: str
    alias: str
    strategy: str
    task_tag: str | None
    candidates: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# Limit Requests Schemas
# ============================================================================


class LimitRequestCreate(BaseModel):
    key_id: str = Field(min_length=1)
    requested_credit_micro: int = Field(gt=0)
    reason: str | None = None


class LimitRequestResponse(BaseModel):
    id: str
    key_id: str
    user_id: str
    requested_credit_micro: int
    status: str
    reason: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LimitRequestApproveRequest(BaseModel):
    approved_credit_micro: int | None = Field(default=None, gt=0)


# ============================================================================
# Usage Schemas
# ============================================================================


class KeyUsageSummary(BaseModel):
    key_id: str
    key_name: str
    key_prefix: str
    credit_limit_micro: int
    credit_remaining_micro: int
    total_requests: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_cost_micro: int
    cost_per_1k_tokens_micro: int


class ModelUsageSummary(BaseModel):
    model: str
    total_requests: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_cost_micro: int
    cost_per_1k_tokens_micro: int


class LedgerEntryResponse(BaseModel):
    id: str
    key_id: str
    amount_micro: int
    balance_after_micro: int
    reason: str
    trace_id: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UsageOverviewResponse(BaseModel):
    total_requests: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_cost_micro: int
    total_credits_remaining_micro: int
    cost_per_1k_tokens_micro: int
    by_key: list[KeyUsageSummary]
    by_model: list[ModelUsageSummary]
    ledger: list[LedgerEntryResponse]
    next_cursor: str | None = None
