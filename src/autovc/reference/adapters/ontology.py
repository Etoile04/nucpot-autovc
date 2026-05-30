"""Ontofuel individual → reference_value adapter.

Converts ontofuel ontology individuals (extracted from papers) into the
reference_value dict format used by the ref-gap-fill pipeline.

Only 4 of 12 target properties have ontofuel key mappings:
  latticeConstant → lattice_constant
  formationEnergy → formation_energy
  meltingPoint    → melting_point
  thermalConductivity → thermal_conductivity

Migrated from material-llm-wiki/scripts/adapter_ontology.py into nucpot-autovc.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# ── Error types ──────────────────────────────────────────────────────────────

class OntologyAdapterError(Exception):
    """Raised when an individual cannot be adapted."""


# ── Data directory ───────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_PROPERTY_MAPPING_FILE = _DATA_DIR / "property-mapping.json"


# ── Class name normalisation ─────────────────────────────────────────────────

_CLASS_TO_ELEMENT: dict[str, str] = {
    "Uranium": "U",
    "Plutonium": "Pu",
    "Molybdenum": "Mo",
    "Zirconium": "Zr",
    "Niobium": "Nb",
    "Iron": "Fe",
    "Chromium": "Cr",
    "Silicon": "Si",
    "Carbon": "C",
    "Nitrogen": "N",
    "Oxygen": "O",
    "Aluminum": "Al",
    "SiliconCarbide": "SiC",
    "UraniumMolybdenumAlloy": "U-Mo",
    "UraniumZirconiumAlloy": "U-Zr",
    "UraniumPlutoniumZirconiumAlloy": "U-Pu-Zr",
    "UraniumSilicide": "U3Si2",
    "UraniumNitride": "UN",
    "UraniumCarbide": "UC",
    "UraniumDioxide": "UO2",
}


def normalize_class_name(class_name: str) -> str:
    """Convert an ontofuel class name to an element_system string.

    Examples:
        "Uranium"               → "U"
        "UraniumMolybdenumAlloy" → "U-Mo"
        "UraniumZirconiumAlloy" → "U-Zr"
        "SiliconCarbide"        → "SiC"
    """
    return _CLASS_TO_ELEMENT.get(class_name, class_name)


# ── Mapping loader ──────────────────────────────────────────────────────────

def _load_ontofuel_key_map() -> dict[str, dict[str, Any]]:
    """Build ontofuel_key → {ref_property, ref_unit, range} lookup.

    Reads reference/data/property-mapping.json and collects every ontofuel_keys entry
    into a flat dict keyed by the ontofuel property name.
    """
    mapping_file = _PROPERTY_MAPPING_FILE
    if not mapping_file.exists():
        raise FileNotFoundError(f"Property mapping not found: {mapping_file}")

    with open(mapping_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    key_map: dict[str, dict[str, Any]] = {}
    for entry in data.get("mappings", []):
        ref_prop = entry["ref_property"]
        ref_unit = entry["ref_unit"]
        prop_range = entry.get("range", {})
        for of_key in entry.get("ontofuel_keys", []):
            key_map[of_key] = {
                "ref_property": ref_prop,
                "ref_unit": ref_unit,
                "range": prop_range,
            }
    return key_map


# ── Module-level cache ─────────────────────────────────────────────────────

_ONTOFUEL_KEY_MAP: dict[str, dict[str, Any]] | None = None


def _get_key_map() -> dict[str, dict[str, Any]]:
    global _ONTOFUEL_KEY_MAP
    if _ONTOFUEL_KEY_MAP is None:
        _ONTOFUEL_KEY_MAP = _load_ontofuel_key_map()
    return _ONTOFUEL_KEY_MAP


# ── Main adapter function ───────────────────────────────────────────────────

def adapt_ontology_individual(individual: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Convert an ontofuel individual into reference_value dicts.

    Parameters
    ----------
    individual : dict
        Must contain "class" (str), "properties" (dict), and optionally "source".

    Returns
    -------
    list[dict] | None
        A list of reference_value dicts for mappable properties, or None/empty
        if no properties match the target set.
    """
    properties = individual.get("properties", {})
    if not properties:
        return None

    class_name = individual.get("class", "")
    element_system = normalize_class_name(class_name)
    source = individual.get("source", "ontofuel extraction")
    key_map = _get_key_map()

    results: list[dict[str, Any]] = []
    for of_key, prop_data in properties.items():
        if of_key not in key_map:
            continue

        mapping = key_map[of_key]
        value = prop_data.get("value")
        unit = prop_data.get("unit", mapping["ref_unit"])

        if value is None:
            continue

        results.append({
            "element_system": element_system,
            "phase": None,
            "property": mapping["ref_property"],
            "value": value,
            "unit": unit,
            "method": None,
            "source": source,
            "source_doi": None,
            "confidence": "medium",
            "uncertainty": None,
            "temperature": None,
        })

    return results if results else None
