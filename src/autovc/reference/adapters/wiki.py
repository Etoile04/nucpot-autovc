"""LLM-wiki parameter → reference_value adapter.

Converts parameters from the llm-wiki knowledge base (Chinese naming)
into the reference_value format used by the Ref-Gap-Fill system.

Migrated from material-llm-wiki/scripts/adapter_wiki.py into nucpot-autovc.
"""

import re

__all__ = ["adapt_wiki_param", "WikiAdapterError"]


class WikiAdapterError(ValueError):
    """Raised when a wiki parameter cannot be adapted."""


# ── Chinese → English property mapping ──────────────────────────────────────
ZH_TO_REF_PROPERTY = {
    "晶格常数": "lattice_constant",
    "内聚能": "cohesive_energy",
    "弹性常数 C11": "C11",
    "弹性常数 C12": "C12",
    "弹性常数 C44": "C44",
    "弹性常数 C33": "C33",
    "体模量": "bulk_modulus",
    "空位形成能": "vacancy_formation_energy",
    "形成能": "formation_energy",
    "表面能": "surface_energy",
    "熔点": "melting_point",
    "热导率": "thermal_conductivity",
}


# ── Unit conversion table ────────────────────────────────────────────────────
UNIT_CONVERSIONS = {
    ("nm", "angstrom"): 10.0,
    ("Bohr", "angstrom"): 0.529177,
    ("Mbar", "GPa"): 100.0,
}


# ── System name normalization rules ────────────────────────────────────────
_SYSTEM_NORMALIZERS = [
    (re.compile(r"[γαβ](-)?(.+)"), lambda m: m.group(2).strip()),  # γ-U → U
    (re.compile(r"(\w+)-\d+wt%(\w+)"), lambda m: f"{m.group(1)}-{m.group(2)}"),  # U-7wt%Mo → U-Mo
    (re.compile(r"bcc\s+(.+)", re.I), lambda m: m.group(1).strip()),  # bcc Mo → Mo
    (re.compile(r"fcc\s+(.+)", re.I), lambda m: m.group(1).strip()),
]


def _normalize_system(system: str) -> str:
    """Normalize alloy/element system name."""
    for pattern, repl in _SYSTEM_NORMALIZERS:
        m = pattern.match(system.strip())
        if m:
            return repl(m)
    return system.strip()


def _parse_temperature(temp_str: str) -> float | None:
    """Parse temperature string like '0K', '300K', 'room temperature'."""
    if not temp_str:
        return None
    s = str(temp_str).strip().lower()
    if s in ("room temperature", "rt", "室温"):
        return 300.0
    m = re.match(r"([-\d.]+)\s*k", s)
    if m:
        return float(m.group(1))
    return None


def _convert_unit(value: float, unit: str) -> tuple[float, str]:
    """Apply unit conversion if applicable."""
    for (src, dst), factor in UNIT_CONVERSIONS.items():
        if unit.strip().lower() == src.lower():
            return round(value * factor, 6), dst
    return value, unit


def _map_property(property_zh: str) -> str:
    """Map Chinese property name to English, with partial-match support."""
    # Try exact match first
    if property_zh in ZH_TO_REF_PROPERTY:
        return ZH_TO_REF_PROPERTY[property_zh]
    # Partial match: if property_zh starts with a key
    for zh_key, en_val in ZH_TO_REF_PROPERTY.items():
        if property_zh.startswith(zh_key):
            return en_val
    raise WikiAdapterError(
        f"Cannot map Chinese property '{property_zh}' to reference property"
    )


def adapt_wiki_param(param: dict) -> dict:
    """Convert an llm-wiki parameter dict to reference_value format.

    Input keys expected:
        system, phase, property_zh, value, unit, temperature, method, source

    Output keys:
        element_system, phase, property, value, unit, method, source,
        source_doi, confidence, uncertainty, temperature
    """
    property_en = _map_property(param["property_zh"])
    raw_value = float(param["value"])
    converted_value, converted_unit = _convert_unit(raw_value, param.get("unit", ""))
    temperature = _parse_temperature(param.get("temperature", ""))

    return {
        "element_system": _normalize_system(param.get("system", "")),
        "phase": param.get("phase", ""),
        "property": property_en,
        "value": converted_value,
        "unit": converted_unit,
        "method": param.get("method", ""),
        "source": param.get("source", ""),
        "source_doi": param.get("source_doi", ""),
        "confidence": str(param.get("confidence", "medium")),
        "uncertainty": param.get("uncertainty"),
        "temperature": temperature,
    }
