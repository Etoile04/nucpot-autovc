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


# ---------------------------------------------------------------------------
# B-B phase: verification history stored in FastAPI local PG (verification_tasks).
# AutoVC schema details (template, progress, current_step, results, etc.)
# are packed into rating_metrics jsonb; potential_function column holds potential_id.
# Potential management still goes to Supabase.
# ---------------------------------------------------------------------------
import json as _json

_LOCAL_PG_DSN = os.environ.get(
    "LOCAL_PG_DSN",
    "postgresql://nfm:local_dev_only_change_me@nucpot-prod-db:5432/nfm_db",
)


def _local_conn():
    """Open a sync psycopg2 connection to local PG.

    Lazy import keeps supabase-only deployments working.
    """
    import psycopg2
    return psycopg2.connect(_LOCAL_PG_DSN)


_STATUS_MAP = {"pending": "queued"}  # autovc → DB enum


def _map_status_in(s: str) -> str:
    return _STATUS_MAP.get(s, s)


def _map_status_out(s: str) -> str:
    # DB 'queued' means 'pending' to autovc callers
    return "pending" if s == "queued" else s


def _row_to_record(row) -> dict:
    """Row layout (13 cols):
        0 id, 1 composition, 2 potential_function, 3 temperature_min,
        4 temperature_max, 5 timestep_count, 6 status, 7 rating,
        8 rating_summary, 9 rating_metrics, 10 error_message, 11 created_at,
        12 updated_at
    """
    extras = row[9] or {}
    if isinstance(extras, str):
        extras = _json.loads(extras)
    return {
        "id": str(row[0]),
        "potential_id": row[2],
        "template": extras.get("template"),
        "status": _map_status_out(row[6]),
        "progress": extras.get("progress", 0.0),
        "current_step": extras.get("current_step"),
        "triggered_by": extras.get("triggered_by"),
        "results": extras.get("results", []),
        "overall_grade": row[7],
        "error_log": row[10],
        "created_at": row[11].isoformat() if row[11] else None,
        "updated_at": row[12].isoformat() if row[12] else None,
    }


async def create_verification(record: dict) -> dict:
    """Insert verification row into local verification_tasks."""
    composition = _json.dumps({"_note": "autovc-record-no-composition"})
    rating_metrics = _json.dumps({
        "template": record.get("template"),
        "progress": record.get("progress", 0.0),
        "current_step": record.get("current_step"),
        "triggered_by": record.get("triggered_by"),
        "results": record.get("results", []),
    })
    with _local_conn() as c:
        with c.cursor() as cur:
            cur.execute(
                """INSERT INTO verification_tasks
                  (id, composition, potential_function, temperature_min, temperature_max,
                   timestep_count, status, rating, rating_summary, rating_metrics, error_message)
                  VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                  RETURNING id""",
                (record["id"], composition, record["potential_id"],
                 0.0, 1000.0, 100, _map_status_in(record.get("status", "queued")),
                 record.get("overall_grade"), None, rating_metrics,
                 record.get("error_log"))
            )
            new_id = cur.fetchone()[0]
            c.commit()
    record["id"] = str(new_id)
    return record


async def update_verification(verification_id: str, updates: dict) -> dict:
    """Partial-update. Known cols mapped to dedicated columns; the rest packed into rating_metrics."""
    set_parts = []
    values = []
    if "status" in updates:
        set_parts.append("status = %s")
        values.append(_map_status_in(updates["status"]))
    if "overall_grade" in updates:
        set_parts.append("rating = %s")
        values.append(updates["overall_grade"])
    if "error_log" in updates:
        set_parts.append("error_message = %s")
        values.append(updates["error_log"])
    with _local_conn() as c:
        with c.cursor() as cur:
            cur.execute("SELECT rating_metrics FROM verification_tasks WHERE id=%s",
                        (verification_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"verification {verification_id} not found")
            extras = row[0] or {}
            if isinstance(extras, str):
                extras = _json.loads(extras)
            for k in ("current_step", "progress", "results"):
                if k in updates:
                    extras[k] = updates[k]
            set_parts.append("rating_metrics = %s::jsonb")
            values.append(_json.dumps(extras))
            set_parts.append("updated_at = NOW()")
            values.append(verification_id)
            sql = f"UPDATE verification_tasks SET {', '.join(set_parts)} WHERE id = %s RETURNING id"
            cur.execute(sql, values)
            c.commit()
    return {"id": verification_id, **updates}


async def get_verification(verification_id: str):
    with _local_conn() as c:
        with c.cursor() as cur:
            cur.execute(
                """SELECT id, composition, potential_function, temperature_min,
                  temperature_max, timestep_count, status, rating, rating_summary,
                  rating_metrics, error_message, created_at, updated_at
                  FROM verification_tasks WHERE id=%s""",
                (verification_id,))
            row = cur.fetchone()
    if not row:
        return None
    return _row_to_record(row)


async def list_verifications(limit: int = 50, offset: int = 0):
    out = []
    with _local_conn() as c:
        with c.cursor() as cur:
            cur.execute(
                """SELECT id, composition, potential_function, temperature_min,
                  temperature_max, timestep_count, status, rating, rating_summary,
                  rating_metrics, error_message, created_at, updated_at
                  FROM verification_tasks ORDER BY created_at DESC LIMIT %s OFFSET %s""",
                (limit, offset))
            for row in cur.fetchall():
                out.append(_row_to_record(row))
    return out
