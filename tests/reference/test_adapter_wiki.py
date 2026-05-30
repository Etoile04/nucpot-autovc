"""Test llm-wiki parameter → reference_value adapter."""
import pytest
from pathlib import Path

from autovc.reference.adapters.wiki import adapt_wiki_param, WikiAdapterError


def test_chinese_name_mapping():
    param = {
        "system": "U-Mo",
        "phase": "BCC",
        "property_zh": "晶格常数",
        "value": 0.343,
        "unit": "nm",
        "temperature": "0K",
        "method": "DFT (PBE)",
        "source": "Hu 2016, JNM",
    }
    result = adapt_wiki_param(param)
    assert result["property"] == "lattice_constant"
    assert abs(result["value"] - 3.43) < 0.01  # nm → Å


def test_elastic_constant_mapping():
    param = {
        "system": "γ-U",
        "phase": "BCC",
        "property_zh": "弹性常数 C11",
        "value": 94,
        "unit": "GPa",
        "temperature": "0K",
        "method": "DFT",
        "source": "Mei 2016",
    }
    result = adapt_wiki_param(param)
    assert result["property"] == "C11"
    assert result["value"] == 94.0


def test_unit_conversion_nm_to_angstrom():
    param = {
        "system": "U-7wt%Mo",
        "phase": "BCC",
        "property_zh": "晶格常数",
        "value": 0.343,
        "unit": "nm",
        "temperature": "0K",
        "method": "DFT",
        "source": "test",
    }
    result = adapt_wiki_param(param)
    assert result["unit"] == "angstrom"
    assert abs(result["value"] - 3.43) < 0.01


def test_unknown_chinese_property_raises():
    param = {
        "system": "U",
        "phase": "BCC",
        "property_zh": "未知性质",
        "value": 1.0,
        "unit": "m",
        "temperature": "0K",
        "method": "test",
        "source": "test",
    }
    with pytest.raises(WikiAdapterError, match="Cannot map"):
        adapt_wiki_param(param)
