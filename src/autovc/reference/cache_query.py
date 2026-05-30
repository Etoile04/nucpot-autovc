"""Three-level cache query for the Ref-Gap-Fill system.

Provides a unified interface to search three data sources for existing
property values:
  L1 — reference_values table (Postgres)
  L2 — NFMD parameters table (Supabase)
  L3 — llm-wiki / ontofuel knowledge base

All external query functions accept mock kwargs so tests run without
real DB connections.

Migrated from material-llm-wiki/scripts/cache_query.py into nucpot-autovc.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class CacheLevel(Enum):
    L1 = "L1"
    L2 = "L2"
    L3A = "L3A"
    L3B = "L3B"


@dataclass
class CacheResult:
    level: CacheLevel
    element_system: str
    phase: str
    property: str
    value: float
    unit: str
    method: str
    source: str
    source_doi: Optional[str] = None
    confidence: str = "high"
    uncertainty: Optional[float] = None
    temperature: float = 0

    def to_ref_value_dict(self) -> dict:
        return {
            "element_system": self.element_system,
            "phase": self.phase,
            "property": self.property,
            "value": self.value,
            "unit": self.unit,
            "method": self.method,
            "source": self.source,
            "source_doi": self.source_doi,
            "confidence": self.confidence,
            "cache_level": self.level.value,
        }


# ---------------------------------------------------------------------------
# Property mapping loader
# ---------------------------------------------------------------------------

MAPPING_PATH = Path(__file__).parent / "data" / "property-mapping.json"


def load_property_mapping() -> dict[str, dict]:
    """Load property-mapping.json and index by ref_property.

    Returns a dict like:
        {
            "lattice_constant": {"ref_unit": "Å", "nfmd_names": [...], ...},
            ...
        }
    """
    with open(MAPPING_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {
        entry["ref_property"]: {
            "ref_unit": entry.get("ref_unit", ""),
            "nfmd_names": entry.get("nfmd_names", []),
            "nfmd_symbols": entry.get("nfmd_symbols", []),
            "ontofuel_keys": entry.get("ontofuel_keys", []),
            "range": entry.get("range", {}),
        }
        for entry in data.get("mappings", [])
    }


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

_UNIT_ALIASES = {
    "Å": "angstrom",
    "angstrom": "angstrom",
    "A": "angstrom",
}


def _normalise_unit(u: str) -> str:
    return _UNIT_ALIASES.get(u, u)


# ---------------------------------------------------------------------------
# L1 — reference_values (Postgres)
# ---------------------------------------------------------------------------

def query_l1(
    element_system: str,
    phase: str,
    property: str,
    *,
    _mock_rows: Optional[list[dict]] = None,
) -> Optional[CacheResult]:
    """Search L1 cache (reference_values) for an exact match.

    Parameters
    ----------
    element_system : str  e.g. "U", "U-10Zr"
    phase          : str  e.g. "BCC", "BCT", "FCC"
    property       : str  canonical ref_property name
    _mock_rows     : list[dict]  rows to use instead of real DB query
    """
    rows = _mock_rows if _mock_rows is not None else []

    for row in rows:
        if (
            row.get("element_system") == element_system
            and row.get("phase") == phase
            and row.get("property") == property
        ):
            return CacheResult(
                level=CacheLevel.L1,
                element_system=element_system,
                phase=phase,
                property=property,
                value=row["value"],
                unit=row.get("unit", ""),
                method=row.get("method", ""),
                source=row.get("source", ""),
                source_doi=row.get("source_doi"),
                confidence="high" if not row.get("needs_review") else "medium",
            )
    return None


# ---------------------------------------------------------------------------
# L2 — NFMD parameters (Supabase)
# ---------------------------------------------------------------------------

def query_l2(
    element_system: str,
    phase: str,
    property: str,
    mapping: dict[str, dict],
    *,
    _mock_params: Optional[list[dict]] = None,
) -> Optional[CacheResult]:
    """Search L2 cache (NFMD parameters) for a matching row.

    Matching logic:
      1. ``material_raw`` must contain the element_system string
      2. ``name`` or ``symbol`` must match one of the mapping's nfmd_names
         or nfmd_symbols for the given property

    Parameters
    ----------
    _mock_params : list[dict]  NFMD param rows to use instead of real DB
    """
    params = _mock_params if _mock_params is not None else []

    prop_info = mapping.get(property)
    if prop_info is None:
        return None

    nfmd_names = {n.lower() for n in prop_info.get("nfmd_names", [])}
    nfmd_symbols = {s.lower() for s in prop_info.get("nfmd_symbols", [])}
    ref_unit = prop_info.get("ref_unit", "")

    for param in params:
        mat = str(param.get("material_raw", ""))
        if element_system.lower() not in mat.lower():
            continue

        name = str(param.get("name", "")).lower()
        symbol = str(param.get("symbol", "")).lower()
        if name not in nfmd_names and symbol not in nfmd_symbols:
            continue

        # Found a match — build result with unit conversion
        raw_unit = _normalise_unit(param.get("unit", ""))
        value = float(param["value_scalar"])

        return CacheResult(
            level=CacheLevel.L2,
            element_system=element_system,
            phase=phase,
            property=property,
            value=value,
            unit=ref_unit or raw_unit,
            method=param.get("method", ""),
            source=param.get("source_file", ""),
            confidence="medium",
            temperature=param.get("temperature_k", 0),
        )
    return None


# ---------------------------------------------------------------------------
# L3 — llm-wiki / ontofuel
# ---------------------------------------------------------------------------

def query_l3_wiki(
    element_system: str,
    property: str,
    *,
    _mock_results: Optional[list[dict]] = None,
) -> Optional[CacheResult]:
    """Search L3 cache (llm-wiki / ontofuel) — placeholder implementation.

    Currently only supports mock data injection.
    """
    results = _mock_results if _mock_results is not None else []

    for item in results:
        if (
            item.get("element_system") == element_system
            and item.get("property") == property
        ):
            return CacheResult(
                level=CacheLevel.L3A,
                element_system=element_system,
                phase=item.get("phase", ""),
                property=property,
                value=item["value"],
                unit=item.get("unit", ""),
                method=item.get("method", "literature"),
                source=item.get("source", "llm-wiki"),
                confidence="low",
            )
    return None


# ---------------------------------------------------------------------------
# Unified orchestrator
# ---------------------------------------------------------------------------

def cache_query(
    element_system: str,
    phase: str,
    property: str,
    *,
    _l1_rows: Optional[list[dict]] = None,
    _l2_params: Optional[list[dict]] = None,
    _l3_results: Optional[list[dict]] = None,
) -> Optional[CacheResult]:
    """Query three cache levels in order: L1 → L2 → L3.

    Returns the first hit, or None if all levels miss.
    """
    # L1 — fastest, most trusted
    result = query_l1(element_system, phase, property, _mock_rows=_l1_rows)
    if result is not None:
        return result

    # L2 — NFMD parameter store
    mapping = load_property_mapping()
    result = query_l2(
        element_system, phase, property, mapping, _mock_params=_l2_params
    )
    if result is not None:
        return result

    # L3 — wiki / ontofuel
    result = query_l3_wiki(element_system, property, _mock_results=_l3_results)
    return result
