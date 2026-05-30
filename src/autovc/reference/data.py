"""Reference data interface for nucpot-autovc.

Drop-in replacement for the original hardcoded _REF dictionary.
Queries the PostgreSQL `reference_values` table, with fallback to
a minimal hardcoded set for development / offline use.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Name mapping: autovc naming → PG reference_values naming
# ---------------------------------------------------------------------------

# autovc uses structure names like "BCC_gamma", PG uses "BCC"
_STRUCTURE_MAP: dict[str, str] = {
    "BCC_gamma": "BCC",
    "BCC": "BCC",
    "FCC": "FCC",
    "HCP": "HCP",
    "diamond": "Diamond",
    "diamond_cubic": "Diamond",
    "SC": "SC",
    "Orthorhombic": "Orthorhombic",
    "Cubic": "Cubic",
}

# autovc uses "elastic_constants_C11" etc., PG uses "C11"
_PROPERTY_MAP: dict[str, str] = {
    "lattice_constant": "lattice_constant",
    "cohesive_energy": "cohesive_energy",
    "bulk_modulus": "bulk_modulus",
    "shear_modulus": "shear_modulus",
    "formation_energy": "formation_energy",
    "C11": "C11",
    "C12": "C12",
    "C44": "C44",
    "elastic_constants_C11": "C11",
    "elastic_constants_C12": "C12",
    "elastic_constants_C44": "C44",
}

# ---------------------------------------------------------------------------
# Hardcoded fallback (same as original _REF)
# ---------------------------------------------------------------------------

_FALLBACK: dict[str, dict[str, dict[str, Any]]] = {
    "U": {
        "BCC_gamma": {
            "lattice_constant": {"value": 3.47, "unit": "angstrom", "source": "Smirnov2014"},
            "cohesive_energy": {"value": -5.49, "unit": "eV/atom", "source": "Smirnov2014"},
            "elastic_constants_C11": {"value": 74.0, "unit": "GPa", "source": "Smirnov2014"},
            "elastic_constants_C12": {"value": 51.0, "unit": "GPa", "source": "Smirnov2014"},
            "elastic_constants_C44": {"value": 73.0, "unit": "GPa", "source": "Smirnov2014"},
        }
    },
    "Mo": {
        "BCC": {
            "lattice_constant": {"value": 3.147, "unit": "angstrom", "source": "exp"},
            "cohesive_energy": {"value": -6.82, "unit": "eV/atom", "source": "exp"},
            "elastic_constants_C11": {"value": 463.0, "unit": "GPa", "source": "exp"},
            "elastic_constants_C12": {"value": 161.0, "unit": "GPa", "source": "exp"},
            "elastic_constants_C44": {"value": 109.0, "unit": "GPa", "source": "exp"},
        }
    },
    "Zr": {
        "BCC": {
            "lattice_constant": {"value": 3.609, "unit": "angstrom", "source": "exp"},
            "cohesive_energy": {"value": -6.25, "unit": "eV/atom", "source": "exp"},
        }
    },
    "U-Mo": {
        "BCC_gamma": {
            "lattice_constant": {"value": 3.39, "unit": "angstrom", "source": "Smirnov2014"},
            "elastic_constants_C11": {"value": 140.0, "unit": "GPa", "source": "Smirnov2014"},
        }
    },
    "U-Zr": {
        "BCC_gamma": {
            "lattice_constant": {"value": 3.52, "unit": "angstrom", "source": "Landa2002"},
        }
    },
}

# ---------------------------------------------------------------------------
# PG query helpers
# ---------------------------------------------------------------------------

_pg_engine = None


def _get_pg_engine():
    """Lazily create SQLAlchemy engine from DATABASE_URL."""
    global _pg_engine
    if _pg_engine is not None:
        return _pg_engine
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return None
    try:
        from sqlalchemy import create_engine
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        _pg_engine = create_engine(url, pool_size=3, max_overflow=5)
        return _pg_engine
    except Exception as e:
        logger.warning(f"Failed to create PG engine: {e}")
        return None


def _query_pg(element_system: str, phase: str, prop: str) -> dict[str, Any] | None:
    """Query reference_values table for a single property."""
    engine = _get_pg_engine()
    if engine is None:
        return None
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT value, unit, source, method, confidence "
                    "FROM reference_values "
                    "WHERE element_system = :sys AND phase = :phase "
                    "AND property = :prop "
                    "ORDER BY confidence DESC, value "
                    "LIMIT 1"
                ),
                {"sys": element_system, "phase": phase, "prop": prop},
            ).fetchone()
            if row is None:
                return None
            return {"value": row[0], "unit": row[1], "source": row[2]}
    except Exception as e:
        logger.debug(f"PG query failed for {element_system}/{phase}/{prop}: {e}")
        return None


def _query_pg_list(column: str) -> list[str]:
    """SELECT DISTINCT column FROM reference_values."""
    engine = _get_pg_engine()
    if engine is None:
        return []
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            rows = conn.execute(text(f"SELECT DISTINCT {column} FROM reference_values ORDER BY {column}")).fetchall()
            return [r[0] for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Public API (same signatures as original)
# ---------------------------------------------------------------------------

def get_reference_value(
    material: str,
    structure: str,
    property_name: str,
) -> dict[str, Any] | None:
    """Look up a reference value.

    Tries PG first, falls back to hardcoded _REF.
    """
    # Map names
    element_system = material  # autovc uses same names as PG for materials
    phase = _STRUCTURE_MAP.get(structure, structure)
    prop = _PROPERTY_MAP.get(property_name, property_name)

    # Try PG
    result = _query_pg(element_system, phase, prop)
    if result is not None:
        return result

    # Fallback to hardcoded
    m = _FALLBACK.get(material)
    if not m:
        return None
    s = m.get(structure)
    if not s:
        return None
    return s.get(property_name)


def list_available_properties() -> list[str]:
    """List all available property names."""
    pg_props = _query_pg_list("property")
    if pg_props:
        return sorted(pg_props)
    # Fallback
    props = set()
    for m in _FALLBACK.values():
        for s in m.values():
            props.update(s.keys())
    return sorted(props)


def list_available_materials() -> list[str]:
    """List all available materials."""
    pg_mats = _query_pg_list("element_system")
    if pg_mats:
        return sorted(pg_mats)
    return sorted(_FALLBACK.keys())


# ---------------------------------------------------------------------------
# New PG-native API (D002-C)
# ---------------------------------------------------------------------------

def query_reference(
    element_system: str,
    phase: str,
    property_name: str,
) -> dict[str, Any] | None:
    """Query reference value using PG-native naming.

    No name mapping — caller must use PG column values directly.
    Returns dict with keys: value, unit, source, method, confidence.
    """
    return _query_pg_full(element_system, phase, property_name)


def _query_pg_full(
    element_system: str, phase: str, prop: str,
) -> dict[str, Any] | None:
    """Query reference_values returning full metadata."""
    engine = _get_pg_engine()
    if engine is None:
        return None
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT value, unit, source, method, confidence "
                    "FROM reference_values "
                    "WHERE element_system = :sys AND phase = :phase "
                    "AND property = :prop "
                    "ORDER BY confidence DESC, value "
                    "LIMIT 1"
                ),
                {"sys": element_system, "phase": phase, "prop": prop},
            ).fetchone()
            if row is None:
                return None
            return {
                "value": row[0], "unit": row[1], "source": row[2],
                "method": row[3], "confidence": row[4],
            }
    except Exception as e:
        logger.debug(f"PG full query failed: {e}")
        return None


# ---------------------------------------------------------------------------
# ORM-based API (for CRUD endpoints)
# ---------------------------------------------------------------------------

def get_reference_from_db(db_session=None):
    """Query ReferenceValue from DB via SQLAlchemy ORM.

    Returns nested dict: {element_system: {phase: {property: {value, unit, source}}}}
    Falls back to _FALLBACK if DB unavailable.
    """
    if db_session is not None:
        try:
            from autovc.models import ReferenceValue
            refs = db_session.query(ReferenceValue).all()
            if refs:
                result = {}
                for r in refs:
                    es = r.element_system
                    phase_key = r.phase or "unknown"
                    result.setdefault(es, {}).setdefault(phase_key, {})[r.property] = {
                        "value": r.value,
                        "unit": r.unit,
                        "source": r.source,
                    }
                return result
        except Exception:
            pass
    return _FALLBACK
