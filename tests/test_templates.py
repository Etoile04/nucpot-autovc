"""Tests for Phase 2 template system."""

import pytest
from autovc.core.templates import (
    get_template,
    list_templates,
    resolve_template_properties,
    TEMPLATE_REGISTRY,
)


class TestTemplateRegistry:
    def test_four_templates_exist(self):
        assert set(TEMPLATE_REGISTRY.keys()) == {"basic", "mechanical", "defect", "comprehensive"}

    def test_basic_template_properties(self):
        t = get_template("basic")
        assert t is not None
        assert "lattice_constant" in t["properties"]
        assert "cohesive_energy" in t["properties"]
        assert len(t["properties"]) == 2

    def test_mechanical_template_includes_elastic(self):
        t = get_template("mechanical")
        assert "elastic_constants" in t["properties"]
        assert "bulk_modulus" in t["properties"]

    def test_defect_template_includes_vacancy(self):
        t = get_template("defect")
        assert "vacancy_formation_energy" in t["properties"]

    def test_comprehensive_has_all_properties(self):
        t = get_template("comprehensive")
        all_props = {"lattice_constant", "cohesive_energy", "elastic_constants", "bulk_modulus", "vacancy_formation_energy"}
        assert set(t["properties"]) == all_props

    def test_template_has_required_fields(self):
        for name, t in TEMPLATE_REGISTRY.items():
            assert "name" in t
            assert "description" in t
            assert "properties" in t
            assert "estimated_time_minutes" in t
            assert "tags" in t
            assert isinstance(t["properties"], list)
            assert isinstance(t["tags"], list)
            assert t["estimated_time_minutes"] > 0

    def test_get_unknown_template_returns_none(self):
        assert get_template("nonexistent") is None


class TestListTemplates:
    def test_returns_list_of_dicts(self):
        templates = list_templates()
        assert len(templates) == 4
        for t in templates:
            assert "id" in t
            assert "name" in t
            assert "properties" in t

    def test_template_ids(self):
        ids = [t["id"] for t in list_templates()]
        assert set(ids) == {"basic", "mechanical", "defect", "comprehensive"}


class TestResolveTemplateProperties:
    def test_default_properties(self):
        props = resolve_template_properties("basic")
        assert props == ["lattice_constant", "cohesive_energy"]

    def test_override_properties(self):
        props = resolve_template_properties("basic", property_overrides=["bulk_modulus"])
        assert props == ["bulk_modulus"]

    def test_override_none_uses_template(self):
        props = resolve_template_properties("mechanical", property_overrides=None)
        assert "elastic_constants" in props

    def test_override_empty_list(self):
        props = resolve_template_properties("basic", property_overrides=[])
        assert props == []

    def test_unknown_template_raises(self):
        with pytest.raises(ValueError, match="Unknown template"):
            resolve_template_properties("nonexistent")
