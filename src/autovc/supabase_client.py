"""Supabase REST API client for fetching potential metadata and managing verifications."""

import asyncio
import logging
import os

import httpx

from autovc.config import get_settings

logger = logging.getLogger(__name__)

_settings = get_settings()

SUPABASE_URL = _settings.SUPABASE_URL or os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = _settings.SUPABASE_SECRET_KEY or os.environ.get("SUPABASE_SECRET_KEY", "")  # sb_secret_... (backend only)

# Transient network failures (GFW interference with the Supabase host) surface
# as SSL EOF / read timeouts / connect resets. These are safe to retry on for
# all our call shapes: reads are idempotent; writes use Prefer=representation
# and are keyed by uuid so a retried POST after a dropped response risks at
# most a duplicate row for create_verification (acceptable + logged).
_MAX_ATTEMPTS = 4
_BACKOFF_BASE = 1.5


def _headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.ConnectTimeout) or isinstance(exc, httpx.ReadTimeout):
        return True
    if isinstance(exc, httpx.HTTPError) and "EOF" in str(exc):
        return True
    # httpx wraps ssl.SSLError inside these; str() can be empty — treat any
    # transport-level HTTPError without a response as transient.
    if isinstance(exc, httpx.TransportError):
        return True
    return False


async def _request_with_retry(method: str, url: str, **kwargs) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError:
            raise  # non-transient: 4xx/5xx from Supabase itself
        except Exception as exc:
            last_exc = exc
            if not _is_transient(exc) or attempt == _MAX_ATTEMPTS:
                raise
            delay = _BACKOFF_BASE ** attempt
            logger.warning(
                "Supabase %s %s transient failure (attempt %d/%d): %s %s — retrying in %.1fs",
                method, url.rsplit("/", 1)[-1], attempt, _MAX_ATTEMPTS,
                type(exc).__name__, str(exc)[:80], delay,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None  # loop always raises or returns before this
    raise last_exc


async def get_potential(potential_id: str) -> dict:
    """Fetch potential metadata from Supabase by UUID."""
    resp = await _request_with_retry(
        "GET",
        f"{SUPABASE_URL}/rest/v1/potentials",
        params={
            "id": f"eq.{potential_id}",
            "select": "id,name,subtype,format,elements,lammps_config,file_url",
        },
        headers=_headers(),
    )
    data = resp.json()
    if not data:
        raise ValueError(f"Potential {potential_id} not found in Supabase")
    return data[0]


async def create_verification(record: dict) -> dict:
    """Insert verification record into Supabase."""
    resp = await _request_with_retry(
        "POST",
        f"{SUPABASE_URL}/rest/v1/verifications",
        json=record,
        headers={**_headers(), "Prefer": "return=representation"},
    )
    return resp.json()[0]


async def update_verification(verification_id: str, updates: dict) -> dict:
    """Update verification record in Supabase."""
    resp = await _request_with_retry(
        "PATCH",
        f"{SUPABASE_URL}/rest/v1/verifications",
        params={"id": f"eq.{verification_id}"},
        json=updates,
        headers={**_headers(), "Prefer": "return=representation"},
    )
    return resp.json()


async def get_verification(verification_id: str) -> dict | None:
    """Fetch a verification record from Supabase."""
    resp = await _request_with_retry(
        "GET",
        f"{SUPABASE_URL}/rest/v1/verifications",
        params={"id": f"eq.{verification_id}", "select": "*"},
        headers=_headers(),
    )
    data = resp.json()
    return data[0] if data else None

async def update_potential(potential_id: str, updates: dict) -> dict:
    """Update potential record in Supabase."""
    resp = await _request_with_retry(
        "PATCH",
        f"{SUPABASE_URL}/rest/v1/potentials",
        params={"id": f"eq.{potential_id}"},
        json=updates,
        headers={**_headers(), "Prefer": "return=representation"},
    )
    return resp.json()
