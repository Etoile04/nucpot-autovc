"""NFMD parameter → reference_value adapter.

Converts parameter records from the Supabase NFMD database into the
reference_value format used by the ref-gap-fill verification service.

Loads property mappings from reference/data/property-mapping.json to translate
NFMD property names/symbols into canonical reference_value property keys.

Migrated from material-llm-wiki/scripts/adapter_nfmd.py into nucpot-autovc.
"""

import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data directory (package-relative)
# ---------------------------------------------------------------------------
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_PROPERTY_MAP_PATH = _DATA_DIR / "property-mapping.json"

# ---------------------------------------------------------------------------
# Unit normalization table
# ---------------------------------------------------------------------------
_UNIT_MAP = {
    "Å": "angstrom",
    "GPa": "GPa",
    "eV": "eV",
    "eV/atom": "eV/atom",
    "J/m²": "J/m²",
    "K": "K",
    "W/m·K": "W/m·K",
}

# ---------------------------------------------------------------------------
# Confidence logic
# ---------------------------------------------------------------------------
_VAGUE_SOURCES = frozenset({"Experiment", "experiment", "Unknown", "unknown", ""})


# ===================================================================
# Custom exception
# ===================================================================
class NfmdAdapterError(Exception):
    """Raised when an NFMD parameter cannot be mapped to a reference_value."""


# ===================================================================
# Mapping loader (cached at module level)
# ===================================================================
def _load_mappings() -> list[dict[str, Any]]:
    """Load property-mapping.json, returning the mappings list."""
    with open(_PROPERTY_MAP_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return data["mappings"]


def _build_lookups(
    mappings: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, str]]:
    """Build name→ref_property and symbol→ref_property lookup dicts.

    Returns (name_lookup, symbol_lookup) where keys are lowercased.
    """
    name_lookup: dict[str, str] = {}
    symbol_lookup: dict[str, str] = {}

    for m in mappings:
        ref_prop = m["ref_property"]
        for name in m.get("nfmd_names", []):
            name_lookup[name.lower()] = ref_prop
        for sym in m.get("nfmd_symbols", []):
            symbol_lookup[sym.lower()] = ref_prop

    return name_lookup, symbol_lookup


# Module-level caches populated on first call to adapt_nfmd_param
_mappings_cache: list[dict[str, Any]] | None = None
_name_lookup_cache: dict[str, str] | None = None
_symbol_lookup_cache: dict[str, str] | None = None


def _ensure_lookups() -> tuple[dict[str, str], dict[str, str]]:
    global _mappings_cache, _name_lookup_cache, _symbol_lookup_cache
    if _mappings_cache is None:
        _mappings_cache = _load_mappings()
        _name_lookup_cache, _symbol_lookup_cache = _build_lookups(_mappings_cache)
    return _name_lookup_cache, _symbol_lookup_cache  # type: ignore[return-value]


# ===================================================================
# Core adaptation function
# ===================================================================
def _resolve_property(name: str, symbol: str) -> str:
    """Try to map an NFMD name/symbol to a canonical ref_property.

    Strategy:
      1. Exact match on symbol (case-insensitive)
      2. Exact match on name (case-insensitive)
      3. Contains match on name (case-insensitive) — longest match wins
    """
    name_lookup, symbol_lookup = _ensure_lookups()

    # 1. Symbol exact match
    if symbol.lower() in symbol_lookup:
        return symbol_lookup[symbol.lower()]

    # 2. Name exact match
    name_lower = name.lower()
    if name_lower in name_lookup:
        return name_lookup[name_lower]

    # 3. Name contains match — find longest matching key
    best_prop = None
    best_len = 0
    for key, ref_prop in name_lookup.items():
        if key in name_lower and len(key) > best_len:
            best_prop = ref_prop
            best_len = len(key)
    if best_prop is not None:
        return best_prop

    raise NfmdAdapterError(
        f"Cannot map NFMD parameter to reference_value: name='{name}', symbol='{symbol}'"
    )


def _normalize_unit(unit: str) -> str:
    """Normalize unit string to canonical form."""
    return _UNIT_MAP.get(unit, unit)


def _compute_confidence(source_file: str) -> str:
    """Heuristic confidence based on source provenance."""
    if source_file.strip() in _VAGUE_SOURCES:
        return "low"
    return "medium"


# ===================================================================
# Public API
# ===================================================================
def adapt_nfmd_param(param: dict[str, Any], phase: str) -> dict[str, Any]:
    """Convert an NFMD parameter record to reference_value format.

    Parameters
    ----------
    param : dict
        NFMD parameter record with keys: material_raw, name, symbol,
        value_scalar, unit, temperature_k, method, source_file.
    phase : str
        Crystal phase (e.g. "BCC", "HCP").

    Returns
    -------
    dict
        reference_value dict with keys: element_system, phase, property,
        value, unit, method, source, source_doi, confidence, uncertainty,
        temperature.

    Raises
    ------
    NfmdAdapterError
        If the property cannot be mapped via name or symbol lookup.
    """
    ref_property = _resolve_property(param["name"], param["symbol"])

    raw_unit = param.get("unit", "")
    norm_unit = _normalize_unit(raw_unit)

    confidence = _compute_confidence(param.get("source_file", ""))

    return {
        "element_system": param["material_raw"],
        "phase": phase,
        "property": ref_property,
        "value": float(param["value_scalar"]),
        "unit": norm_unit,
        "method": param.get("method", ""),
        "source": param.get("source_file", ""),
        "source_doi": "",
        "confidence": confidence,
        "uncertainty": None,
        "temperature": float(param.get("temperature_k", 0)),
    }
