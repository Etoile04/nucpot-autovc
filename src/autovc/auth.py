"""Authentication & authorization for AutoVC API.

Sprint 2 — API Key based auth with optional role support.

Supports two token sources:
  1. Authorization: Bearer <key>
  2. Cookie: access_token=<key>

Key validation:
  - API Keys are prefixed with ``avc_`` and validated via constant-time compare.
  - Admin keys are a separate list; admin endpoints require admin role.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, Request

from autovc.config import get_settings


@dataclass(frozen=True)
class AuthPayload:
    """Authenticated identity returned by ``require_auth``."""
    role: Literal["user", "admin"]
    key_id: str  # first 8 chars of the key (for audit logging)


def _constant_time_compare(a: str, b: str) -> bool:
    """HMAC-based constant-time string comparison."""
    return hmac.compare_digest(a.encode(), b.encode())


def _hash_key(key: str) -> str:
    """SHA-256 hash of the raw key for storage/comparison."""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Generate a new API key.

    Returns (raw_key, key_id) where key_id is the short prefix for logging.
    """
    raw = f"avc_{secrets.token_urlsafe(32)}"
    key_id = raw[:12]
    return raw, key_id


def _extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    return request.cookies.get("access_token")


def _validate_key(raw_token: str, valid_hashes: list[str]) -> bool:
    """Check raw token against a list of pre-hashed keys."""
    token_hash = _hash_key(raw_token)
    return any(_constant_time_compare(token_hash, h) for h in valid_hashes)


def require_auth(request: Request) -> AuthPayload:
    """FastAPI dependency — authenticate via API key.

    Reads ``AUTH_API_KEYS_HASHED`` (comma-separated SHA-256 hashes) from settings.
    If ``AUTH_ADMIN_KEYS_HASHED`` is set, keys in that list get role=admin;
    otherwise all authenticated users are admin (backward compat for single-user).
    """
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    settings = get_settings()
    api_hashes = [h.strip() for h in settings.AUTH_API_KEYS_HASHED.split(",") if h.strip()]
    admin_hashes = [h.strip() for h in settings.AUTH_ADMIN_KEYS_HASHED.split(",") if h.strip()] if settings.AUTH_ADMIN_KEYS_HASHED else []

    if not api_hashes:
        # No keys configured — pass through (dev mode)
        # TODO: log a warning once at startup instead of per-request
        return AuthPayload(role="admin", key_id="dev-mode")

    if not _validate_key(token, api_hashes):
        raise HTTPException(status_code=401, detail="Invalid API key")

    key_id = token[:12] if len(token) >= 12 else token
    if admin_hashes and _validate_key(token, admin_hashes):
        return AuthPayload(role="admin", key_id=key_id)
    elif not admin_hashes:
        # No admin list configured — all keys are admin (single-user mode)
        return AuthPayload(role="admin", key_id=key_id)
    else:
        return AuthPayload(role="user", key_id=key_id)


def require_admin(request: Request) -> AuthPayload:
    """FastAPI dependency — require admin role.

    Wraps ``require_auth`` and additionally checks role.
    """
    payload = require_auth(request)
    if payload.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload
