#!/usr/bin/env python3
"""T4: Bulk verification submission — 12 properties × 14 systems.

Submits verification jobs via the autovc API for all supported potentials.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

API_BASE = "http://localhost:8002/api"

# Properties verified by autovc per template
TEMPLATE_PROPERTIES = {
    "basic": ["lattice_constant", "cohesive_energy"],
    "mechanical": ["lattice_constant", "cohesive_energy", "elastic_constants", "bulk_modulus"],
    "defect": ["vacancy_formation_energy", "surface_energy"],
    "comprehensive": ["lattice_constant", "cohesive_energy", "elastic_constants", "bulk_modulus",
                       "vacancy_formation_energy", "surface_energy"],
}

# Supported potential types for LAMMPS verification
SUPPORTED_TYPES = {"EAM", "MEAM", "EAM/FS", "FS", "MTP"}

# Structures per element
DEFAULT_STRUCTURES = {
    "U": "bcc", "Mo": "bcc", "Zr": "hcp", "Nb": "bcc", "W": "bcc",
    "Fe": "bcc", "Cr": "bcc", "Ti": "hcp", "Ni": "fcc", "Cu": "fcc",
    "Al": "fcc", "Hf": "hcp", "Ta": "bcc", "V": "bcc", "Re": "hcp",
    "Si": "diamond", "C": "diamond", "He": "fcc",
}

# Alloy structure mapping
ALLOY_STRUCTURES = {
    "U-Mo": "bcc", "U-Zr": "bcc", "U-Nb": "bcc", "U-Pu": "bcc",
    "Zr-Nb": "bcc", "Fe-Cr": "bcc", "W-Re": "bcc", "W-Ta": "bcc",
    "W-V": "bcc", "W-Mo": "bcc", "Fe-Ni": "fcc", "Fe-Cr-Ni": "fcc",
    "Fe-Cr-Al": "bcc", "W-Ta-V-Cr": "bcc", "W-Ni-Fe": "bcc",
    "W-Ta-He": "bcc", "W-Ta-V-Cr-He": "bcc",
}


def get_potentials(client: httpx.Client) -> list[dict]:
    """Fetch all potentials from Supabase via the API."""
    # Direct Supabase query since API doesn't have list potentials
    import os
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SECRET_KEY", "")
    if not url or not key:
        # Load from .env
        env_file = Path(__file__).parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("SUPABASE_URL="):
                    url = line.split("=", 1)[1].strip()
                elif line.startswith("SUPABASE_SECRET_KEY="):
                    key = line.split("=", 1)[1].strip()

    if not url or not key:
        print("ERROR: SUPABASE_URL or SUPABASE_SECRET_KEY not set")
        sys.exit(1)

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    r = client.get(f"{url}/rest/v1/potentials", headers=headers,
                   params={"select": "id,name,type,elements,system_name", "limit": "200"})
    return r.json()


def should_verify(potential: dict) -> bool:
    """Check if a potential should be verified."""
    ptype = (potential.get("type") or "").upper()
    # Support EAM, MEAM, FS, EAM/FS, MTP
    return ptype in {"EAM", "MEAM", "FS", "EAM/FS", "MTP"}


def get_structure(potential: dict) -> str | None:
    """Determine crystal structure for a potential."""
    elements = potential.get("elements", [])
    system = potential.get("system_name", "")

    # Check alloy structure mapping
    for alloy, struct in ALLOY_STRUCTURES.items():
        if alloy in system:
            return struct

    # Single element: use default
    if len(elements) == 1:
        return DEFAULT_STRUCTURES.get(elements[0])

    # Multi-element: default BCC for nuclear materials
    if len(elements) > 1:
        return "bcc"

    return None


def main():
    parser = argparse.ArgumentParser(description="Bulk verify potentials")
    parser.add_argument("--dry-run", action="store_true", help="Only print what would be submitted")
    parser.add_argument("--template", default="basic", choices=["basic", "mechanical", "defect", "comprehensive"])
    parser.add_argument("--max-jobs", type=int, default=0, help="Max jobs to submit (0=all)")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between submissions (seconds)")
    args = parser.parse_args()

    client = httpx.Client(timeout=30)
    potentials = get_potentials(client)

    eligible = [p for p in potentials if should_verify(p)]
    print(f"Total potentials: {len(potentials)}")
    print(f"Eligible for verification: {len(eligible)}")
    print(f"Template: {args.template}")
    print(f"Properties: {TEMPLATE_PROPERTIES[args.template]}")
    print()

    submitted = 0
    skipped = 0
    errors = []

    for p in eligible:
        pid = p["id"]
        name = p["name"]
        structure = get_structure(p)

        if args.max_jobs > 0 and submitted >= args.max_jobs:
            print(f"\n Reached max jobs limit ({args.max_jobs})")
            break

        print(f"  [{submitted+1}] {name} | type={p.get('type')} | struct={structure}")

        if args.dry_run:
            submitted += 1
            continue

        # Submit via API
        try:
            body = {
                "potential_id": pid,
                "template": args.template,
                "triggered_by": "scheduler_bulk",
            }
            if structure:
                body["structure"] = structure

            r = client.post(f"{API_BASE}/verify", json=body)
            if r.status_code == 200:
                data = r.json()
                job_id = data.get("job_id") or data.get("id", "?")
                print(f"      → submitted: {job_id}")
                submitted += 1
            else:
                print(f"      → ERROR {r.status_code}: {r.text[:100]}")
                errors.append((name, r.status_code, r.text[:100]))
                skipped += 1
        except Exception as e:
            print(f"      → EXCEPTION: {e}")
            errors.append((name, 0, str(e)[:100]))
            skipped += 1

        if submitted > 0 and submitted % 5 == 0:
            print(f"\n  Progress: {submitted} submitted, {skipped} errors\n")

        if not args.dry_run:
            time.sleep(args.delay)

    print(f"\n{'='*60}")
    print(f"DONE: {submitted} submitted, {skipped} errors")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for name, code, msg in errors:
            print(f"  {name}: HTTP {code} — {msg}")


if __name__ == "__main__":
    main()
