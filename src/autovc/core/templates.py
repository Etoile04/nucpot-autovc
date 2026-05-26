"""Verification templates for common property sets.

Each template defines a curated list of properties, descriptions,
and estimated computation time for different verification scenarios.
"""

from __future__ import annotations

from typing import Any


TEMPLATE_REGISTRY: dict[str, dict[str, Any]] = {
    "basic": {
        "name": "Basic",
        "description": "Quick validation of lattice constant and cohesive energy",
        "properties": ["lattice_constant", "cohesive_energy"],
        "estimated_time_minutes": 5,
        "tags": ["quick", "essential"],
    },
    "mechanical": {
        "name": "Mechanical",
        "description": "Elastic properties and bulk modulus for mechanical behavior",
        "properties": ["lattice_constant", "cohesive_energy", "elastic_constants", "bulk_modulus"],
        "estimated_time_minutes": 15,
        "tags": ["mechanical", "elastic"],
    },
    "defect": {
        "name": "Defect",
        "description": "Point defect properties including vacancy formation energy",
        "properties": ["lattice_constant", "cohesive_energy", "vacancy_formation_energy"],
        "estimated_time_minutes": 20,
        "tags": ["defect", "vacancy"],
    },
    "comprehensive": {
        "name": "Comprehensive",
        "description": "Full property suite including elastic, defect, and thermal properties",
        "properties": [
            "lattice_constant",
            "cohesive_energy",
            "elastic_constants",
            "bulk_modulus",
            "vacancy_formation_energy",
        ],
        "estimated_time_minutes": 30,
        "tags": ["full", "comprehensive"],
    },
}


def get_template(name: str) -> dict[str, Any] | None:
    """Get a template by name. Returns None if not found."""
    return TEMPLATE_REGISTRY.get(name)


def list_templates() -> list[dict[str, Any]]:
    """List all available templates with metadata."""
    return [
        {
            "id": key,
            "name": val["name"],
            "description": val["description"],
            "properties": val["properties"],
            "estimated_time_minutes": val["estimated_time_minutes"],
            "tags": val["tags"],
        }
        for key, val in TEMPLATE_REGISTRY.items()
    ]


def resolve_template_properties(
    template_name: str,
    property_overrides: list[str] | None = None,
) -> list[str]:
    """Resolve final property list from template + overrides.

    If property_overrides is provided, it replaces the template's property list.
    Otherwise returns the template's default properties.
    """
    tmpl = get_template(template_name)
    if tmpl is None:
        raise ValueError(f"Unknown template: {template_name}")

    if property_overrides is not None:
        return property_overrides

    return list(tmpl["properties"])
