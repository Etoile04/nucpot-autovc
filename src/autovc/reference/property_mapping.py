"""Property mapping: load and query the canonical property-mapping.json.

Exports:
    PROPERTY_MAPPING   – dict keyed by ref_property name
    get_property_mapping() – reload/return the mapping dict
    is_valid_property(prop_name) – check if a property is known
    get_range(prop_name) – return (min, max) for a known property
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Path resolution — JSON sits alongside this file under data/
# ---------------------------------------------------------------------------
_DATA_DIR = Path(__file__).parent / "data"
_MAPPING_FILE = _DATA_DIR / "property-mapping.json"

# Module-level cache: loaded once on first access
_PROPERTY_MAPPING_CACHE: Optional[dict] = None


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _load_raw() -> dict:
    """Read and parse property-mapping.json (no caching)."""
    with open(_MAPPING_FILE, encoding="utf-8") as f:
        return json.load(f)


def _build_index(raw: dict) -> dict[str, dict]:
    """Index the flat ``mappings`` list by ``ref_property``."""
    return {
        entry["ref_property"]: {
            "unit": entry.get("ref_unit", ""),
            "range": entry.get("range", {}),
            "nfmd_names": entry.get("nfmd_names", []),
            "nfmd_symbols": entry.get("nfmd_symbols", []),
            "ontofuel_keys": entry.get("ontofuel_keys", []),
        }
        for entry in raw.get("mappings", [])
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_property_mapping() -> dict[str, dict]:
    """Return (and cache) the property mapping dict keyed by ref_property.

    Each value has keys: unit, range, nfmd_names, nfmd_symbols, ontofuel_keys.
    """
    global _PROPERTY_MAPPING_CACHE
    if _PROPERTY_MAPPING_CACHE is None:
        _PROPERTY_MAPPING_CACHE = _build_index(_load_raw())
    return _PROPERTY_MAPPING_CACHE


# Convenience alias — allows ``from autovc.reference.property_mapping import PROPERTY_MAPPING``
PROPERTY_MAPPING: dict[str, dict] = {}  # populated at import time

# Populate on module load so that direct import of PROPERTY_MAPPING works.
# Uses a try/except so the module is importable even if the JSON file is
# missing (e.g. during testing or before data is bundled).
try:
    _PROPERTY_MAPPING_CACHE = _build_index(_load_raw())
    PROPERTY_MAPPING = _PROPERTY_MAPPING_CACHE
except FileNotFoundError:
    pass


def is_valid_property(prop_name: str) -> bool:
    """Check whether *prop_name* is a known canonical property."""
    return prop_name in get_property_mapping()


def get_range(prop_name: str) -> tuple[float, float]:
    """Return ``(min, max)`` for a known property, or ``(0.0, 0.0)`` if unknown."""
    mapping = get_property_mapping()
    info = mapping.get(prop_name)
    if info is None:
        return (0.0, 0.0)
    r = info.get("range", {})
    return (float(r.get("min", 0.0)), float(r.get("max", 0.0)))
