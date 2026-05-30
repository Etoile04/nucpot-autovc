"""write_ref_value: quality gate, dedup, and confidence-based write for reference values.

This module is the final gatekeeper before data enters the reference_values table.
It enforces:
  1. Quality gate: source required + value within property range
  2. Deduplication: unique by (element_system, phase, property, method, source)
  3. Confidence-based write: high -> WRITTEN_AUTO, medium/low -> WRITTEN_PENDING_REVIEW

Migrated from material-llm-wiki/scripts/write_ref_value.py into nucpot-autovc.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parent / "data"
_PROPERTY_MAPPING_FILE = _DATA_DIR / "property-mapping.json"

_DEDUP_FIELDS = ("element_system", "phase", "property", "method", "source")


def _load_property_ranges() -> dict[str, dict]:
    """Load ref_property -> range mapping from property-mapping.json."""
    with open(_PROPERTY_MAPPING_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        m["ref_property"]: m["range"]
        for m in data.get("mappings", [])
        if "range" in m
    }


# Lazy-loaded singleton
_PROPERTY_RANGES: Optional[dict[str, dict]] = None


def _get_property_ranges() -> dict[str, dict]:
    global _PROPERTY_RANGES
    if _PROPERTY_RANGES is None:
        _PROPERTY_RANGES = _load_property_ranges()
    return _PROPERTY_RANGES


# ---------------------------------------------------------------------------
# Enums / dataclasses
# ---------------------------------------------------------------------------


class WriteStatus(Enum):
    WRITTEN_AUTO = "written_auto"
    WRITTEN_PENDING_REVIEW = "written_pending_review"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass
class WriteResult:
    status: WriteStatus
    reason: str = ""
    record_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def passes_range_check(property_name: str, value: float) -> bool:
    """Check *value* against the allowed range for *property_name*.

    Returns True when the property has no defined range or when the value
    falls within [min, max].  Returns False otherwise.
    """
    ranges = _get_property_ranges()
    r = ranges.get(property_name)
    if r is None:
        return True  # unknown property — allow (fail-open)
    return r["min"] <= value <= r["max"]


def passes_quality_gate(ref: dict) -> bool:
    """Quality gate: source must be non-empty AND value must pass range check."""
    source = (ref.get("source") or "").strip()
    if not source:
        return False
    return passes_range_check(ref.get("property", ""), ref.get("value", 0))


def dedup_check(ref: dict, existing: list[dict]) -> bool:
    """Return True if *ref* is a duplicate of a record already in *existing*.

    Uniqueness key: (element_system, phase, property, method, source).
    """
    def _key(r: dict) -> tuple:
        return tuple(str(r.get(k, "")).strip() for k in _DEDUP_FIELDS)

    ref_key = _key(ref)
    return any(_key(e) == ref_key for e in existing)


def write_ref_value(
    ref: dict,
    _existing: Optional[list[dict]] = None,
) -> WriteResult:
    """Evaluate and (conceptually) write a reference value record.

    Parameters
    ----------
    ref : dict
        Candidate record with at least: element_system, phase, property,
        value, unit, method, source, confidence.
    _existing : list[dict] or None
        Existing records for dedup.  When None the real API would be queried
        (not yet implemented — this parameter is required for tests).

    Returns
    -------
    WriteResult with status and reason.
    """
    existing = _existing if _existing is not None else []

    # 1. Quality gate
    if not passes_quality_gate(ref):
        source = (ref.get("source") or "").strip()
        if not source:
            return WriteResult(WriteStatus.REJECTED, reason="missing source")
        return WriteResult(
            WriteStatus.REJECTED,
            reason=f"value {ref.get('value')} out of range for {ref.get('property')}",
        )

    # 2. Dedup
    if dedup_check(ref, existing):
        return WriteResult(WriteStatus.DUPLICATE, reason="duplicate record")

    # 3. Confidence-based write
    confidence = (ref.get("confidence") or "").strip().lower()
    if confidence == "high":
        return WriteResult(WriteStatus.WRITTEN_AUTO, reason="high confidence — auto-written")
    else:
        return WriteResult(
            WriteStatus.WRITTEN_PENDING_REVIEW,
            reason=f"confidence '{confidence}' — needs review",
        )
