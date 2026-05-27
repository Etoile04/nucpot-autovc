"""Supabase REST API client for fetching potential metadata and managing verifications."""

import os
import httpx

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


async def get_potential(potential_id: str) -> dict:
    """Fetch potential metadata from Supabase by UUID."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/potentials",
            params={
                "id": f"eq.{potential_id}",
                "select": "id,name,type,format,elements,lammps_config,file_url",
            },
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise ValueError(f"Potential {potential_id} not found in Supabase")
        return data[0]


async def create_verification(record: dict) -> dict:
    """Insert verification record into Supabase."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/verifications",
            json=record,
            headers={**_headers(), "Prefer": "return=representation"},
        )
        resp.raise_for_status()
        return resp.json()[0]


async def update_verification(verification_id: str, updates: dict) -> dict:
    """Update verification record in Supabase."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.patch(
            f"{SUPABASE_URL}/rest/v1/verifications",
            params={"id": f"eq.{verification_id}"},
            json=updates,
            headers={**_headers(), "Prefer": "return=representation"},
        )
        resp.raise_for_status()
        return resp.json()


async def get_verification(verification_id: str) -> dict | None:
    """Fetch a verification record from Supabase."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/verifications",
            params={"id": f"eq.{verification_id}", "select": "*"},
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else None
