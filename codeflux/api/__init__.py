from __future__ import annotations

from codeflux.api.arena import router as arena_router
from codeflux.api.auth import router as auth_router
from codeflux.api.demo import demo_router
from codeflux.api.explain import router as explain_router
from codeflux.api.keys import router as keys_router
from codeflux.api.playground import router as playground_router
from codeflux.api.requests import admin_router as admin_requests_router
from codeflux.api.requests import member_router as member_requests_router
from codeflux.api.requests import traces_router as admin_traces_router
from codeflux.api.routes import router as routes_router
from codeflux.api.sessions import router as member_sessions_router
from codeflux.api.usage import admin_usage_router, member_usage_router
from codeflux.api.vault import router as vault_router

__all__ = [
    "admin_requests_router",
    "admin_traces_router",
    "admin_usage_router",
    "arena_router",
    "auth_router",
    "demo_router",
    "explain_router",
    "keys_router",
    "member_requests_router",
    "member_sessions_router",
    "member_usage_router",
    "playground_router",
    "routes_router",
    "vault_router",
]
