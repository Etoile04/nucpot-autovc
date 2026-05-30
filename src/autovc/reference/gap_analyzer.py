"""Gap analyzer: compare target matrix vs existing data to find missing property tuples.

Identifies gaps in the reference property coverage by comparing a defined
target matrix of (element_system, phase, property) tuples against existing
reference data. Results are sorted by priority for systematic fill operations.

Migrated from material-llm-wiki/scripts/gap_analyzer.py into nucpot-autovc.
"""

from dataclasses import dataclass, asdict

TARGET_SYSTEMS = [
    {"element_system": "U", "phase": "BCC", "priority": 1},
    {"element_system": "Mo", "phase": "BCC", "priority": 1},
    {"element_system": "Zr", "phase": "BCC", "priority": 1},
    {"element_system": "Zr", "phase": "HCP", "priority": 1},
    {"element_system": "Nb", "phase": "BCC", "priority": 1},
    {"element_system": "U-Mo", "phase": "BCC", "priority": 1},
    {"element_system": "U-Zr", "phase": "BCC", "priority": 2},
    {"element_system": "U-Nb", "phase": "BCC", "priority": 2},
    {"element_system": "U-Pu", "phase": "BCC", "priority": 2},
    {"element_system": "U-Pu-Zr", "phase": "BCC", "priority": 2},
    {"element_system": "Pu", "phase": "BCC", "priority": 2},
    {"element_system": "Fe", "phase": "BCC", "priority": 3},
    {"element_system": "Cr", "phase": "BCC", "priority": 3},
    {"element_system": "SiC", "phase": None, "priority": 3},
]

REQUIRED_PROPERTIES = [
    "lattice_constant", "cohesive_energy",
    "C11", "C12", "C44", "C33",
    "bulk_modulus", "vacancy_formation_energy",
]


@dataclass
class GapItem:
    element_system: str
    phase: str
    property: str
    priority: int

    def to_dict(self):
        return asdict(self)


def load_target_systems() -> list[dict]:
    """Return TARGET_SYSTEMS with REQUIRED_PROPERTIES added to each entry."""
    return [{**s, "properties": REQUIRED_PROPERTIES} for s in TARGET_SYSTEMS]


def load_existing_refs(refs: list[dict]) -> set[tuple[str, str, str]]:
    """Convert list of reference dicts to set of (element_system, phase, property) tuples."""
    result: set[tuple[str, str, str]] = set()
    for r in refs:
        result.add((r["element_system"], r["phase"], r["property"]))
    return result


def compute_gaps(targets: list[dict], existing_set: set[tuple[str, str, str]]) -> list[GapItem]:
    """Compute missing (element_system, phase, property) tuples, sorted by priority ascending."""
    gaps: list[GapItem] = []
    for t in targets:
        for prop in t["properties"]:
            key = (t["element_system"], t["phase"], prop)
            if key not in existing_set:
                gaps.append(GapItem(
                    element_system=t["element_system"],
                    phase=t["phase"],
                    property=prop,
                    priority=t["priority"],
                ))
    gaps.sort(key=lambda g: (g.priority, g.element_system, g.phase, g.property))
    return gaps
