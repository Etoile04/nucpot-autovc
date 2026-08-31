"""Tests for the reference value lookup contract (NFM-3873 / BUG-20).

The legacy ``_get_ref_value`` returned ``float | None`` and silently
substituted a hardcoded ``lattice_guess`` (default 3.4 Å) for ``lattice_constant``
when PG / _FALLBACK had no entry. Callers grading results then computed
grades against an *optimization initial guess* — producing the W-Ta
"reference=3.4, grade=C" misfire documented in BUG-20.

These tests pin down the new contract: a lookup result carries an
explicit flag so callers can distinguish a real reference from a dev
fallback or a miss. Prod environment must never use the lattice fallback.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from autovc.runners.reference_lookup import (
    LATTICE_GUESS,
    ReferenceFlag,
    ReferenceLookup,
    get_initial_lattice_guess,
    lookup_reference,
)


# ---------------------------------------------------------------------------
# ReferenceFlag enum
# ---------------------------------------------------------------------------


def test_reference_flag_values_are_distinct():
    assert ReferenceFlag.REFERENCE_OK != ReferenceFlag.REFERENCE_MISSING
    assert ReferenceFlag.REFERENCE_OK != ReferenceFlag.DEV_FALLBACK
    assert ReferenceFlag.REFERENCE_MISSING != ReferenceFlag.DEV_FALLBACK


def test_reference_flag_string_values_match_contract():
    assert ReferenceFlag.REFERENCE_OK.value == "reference_ok"
    assert ReferenceFlag.REFERENCE_MISSING.value == "reference_missing"
    assert ReferenceFlag.DEV_FALLBACK.value == "dev_fallback"


# ---------------------------------------------------------------------------
# ReferenceLookup dataclass
# ---------------------------------------------------------------------------


def test_reference_lookup_is_real_reference_only_when_ok():
    ok = ReferenceLookup(value=3.4, flag=ReferenceFlag.REFERENCE_OK)
    miss = ReferenceLookup(value=None, flag=ReferenceFlag.REFERENCE_MISSING)
    fb = ReferenceLookup(value=3.4, flag=ReferenceFlag.DEV_FALLBACK)

    assert ok.is_real_reference is True
    assert miss.is_real_reference is False
    assert fb.is_real_reference is False  # dev fallback is NOT a real reference


def test_reference_lookup_is_frozen():
    """ReferenceLookup must be immutable so callers can't silently mutate flag."""
    r = ReferenceLookup(value=3.4, flag=ReferenceFlag.REFERENCE_OK)
    with pytest.raises((AttributeError, Exception)):
        r.flag = ReferenceFlag.REFERENCE_MISSING  # type: ignore[misc]


# ---------------------------------------------------------------------------
# lookup_reference — happy path (PG hit)
# ---------------------------------------------------------------------------


def test_lookup_reference_returns_ok_when_pg_has_value():
    """When PG returns a value, lookup_reference must mark REFERENCE_OK."""
    pg_payload = {"value": 3.47, "unit": "angstrom", "source": "Smirnov2014"}
    with patch(
        "autovc.reference.data.get_reference_value", return_value=pg_payload,
    ):
        result = lookup_reference("U", "BCC", "lattice_constant", env="production")
    assert result.flag is ReferenceFlag.REFERENCE_OK
    assert result.value == pytest.approx(3.47)
    assert result.is_real_reference is True


def test_lookup_reference_ok_for_cohesive_energy_when_pg_has_value():
    pg_payload = {"value": -5.49, "unit": "eV/atom", "source": "Smirnov2014"}
    with patch(
        "autovc.reference.data.get_reference_value", return_value=pg_payload,
    ):
        result = lookup_reference("U", "BCC", "cohesive_energy", env="production")
    assert result.flag is ReferenceFlag.REFERENCE_OK
    assert result.value == pytest.approx(-5.49)


# ---------------------------------------------------------------------------
# lookup_reference — miss path (BUG-20 regression)
# ---------------------------------------------------------------------------


def test_lookup_reference_missing_returns_null_and_flag_not_fallback_in_prod():
    """W-Ta regression: in prod, missing PG/REF must return reference_missing,
    NOT a lattice_guess default. Caller can then refuse to grade.
    """
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        result = lookup_reference("W-Ta", "BCC", "lattice_constant", env="production")
    assert result.value is None
    assert result.flag is ReferenceFlag.REFERENCE_MISSING
    assert result.is_real_reference is False


def test_lookup_reference_missing_for_non_lattice_property_never_falls_back():
    """cohesive_energy etc. have no fallback — must always be missing in prod."""
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        result = lookup_reference("W-Ta", "BCC", "cohesive_energy", env="dev")
    assert result.value is None
    assert result.flag is ReferenceFlag.REFERENCE_MISSING


def test_lookup_reference_missing_for_C11_never_falls_back():
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        result = lookup_reference("W-Ta", "BCC", "C11", env="dev")
    assert result.value is None
    assert result.flag is ReferenceFlag.REFERENCE_MISSING


# ---------------------------------------------------------------------------
# lookup_reference — dev fallback (only for lattice_constant, only in dev)
# ---------------------------------------------------------------------------


def test_lookup_reference_dev_fallback_for_lattice_in_dev_env():
    """In dev, lattice_constant miss returns the dev fallback and is flagged."""
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        result = lookup_reference(
            "W-Ta", "BCC", "lattice_constant", env="dev",
        )
    assert result.flag is ReferenceFlag.DEV_FALLBACK
    # Default guess used when material not in LATTICE_GUESS
    assert result.value == pytest.approx(LATTICE_GUESS.get("W-Ta", 3.4))
    # Crucially: a dev fallback must NOT be classified as a real reference.
    assert result.is_real_reference is False


def test_lookup_reference_dev_fallback_uses_known_material_value():
    """Materials in LATTICE_GUESS get their specific value in dev fallback."""
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        result = lookup_reference("U", "BCC", "lattice_constant", env="dev")
    assert result.flag is ReferenceFlag.DEV_FALLBACK
    assert result.value == pytest.approx(LATTICE_GUESS["U"])


def test_lookup_reference_prod_never_uses_lattice_fallback():
    """Even for known materials (e.g. U), prod must NOT use the dev fallback."""
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        result = lookup_reference("U", "BCC", "lattice_constant", env="production")
    assert result.value is None
    assert result.flag is ReferenceFlag.REFERENCE_MISSING


@pytest.mark.parametrize("env", ["production", "staging", "prod", "PRODUCTION"])
def test_lookup_reference_prod_like_envs_never_fall_back(env):
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        result = lookup_reference("W-Ta", "BCC", "lattice_constant", env=env)
    assert result.flag is ReferenceFlag.REFERENCE_MISSING, (
        f"env={env!r} unexpectedly used the lattice fallback"
    )


@pytest.mark.parametrize("env", ["dev", "development", "local", "test"])
def test_lookup_reference_dev_like_envs_may_fall_back(env):
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        result = lookup_reference("W-Ta", "BCC", "lattice_constant", env=env)
    assert result.flag is ReferenceFlag.DEV_FALLBACK, (
        f"env={env!r} should allow the lattice fallback"
    )


# ---------------------------------------------------------------------------
# Environment detection (NUCPOT_ENV / NFM_ENV)
# ---------------------------------------------------------------------------


def test_lookup_reference_picks_up_dev_env_from_environ(monkeypatch):
    monkeypatch.setenv("NUCPOT_ENV", "dev")
    monkeypatch.delenv("NFM_ENV", raising=False)
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        result = lookup_reference("W-Ta", "BCC", "lattice_constant")
    assert result.flag is ReferenceFlag.DEV_FALLBACK


def test_lookup_reference_picks_up_prod_env_from_environ(monkeypatch):
    monkeypatch.setenv("NUCPOT_ENV", "production")
    monkeypatch.delenv("NFM_ENV", raising=False)
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        result = lookup_reference("W-Ta", "BCC", "lattice_constant")
    assert result.flag is ReferenceFlag.REFERENCE_MISSING


def test_lookup_reference_defaults_to_prod_when_no_env_var(monkeypatch):
    """Fail-safe: no env var → treat as production (no fallback)."""
    monkeypatch.delenv("NUCPOT_ENV", raising=False)
    monkeypatch.delenv("NFM_ENV", raising=False)
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        result = lookup_reference("W-Ta", "BCC", "lattice_constant")
    assert result.flag is ReferenceFlag.REFERENCE_MISSING


# ---------------------------------------------------------------------------
# get_initial_lattice_guess — separate API for the LAMMPS initial guess
# ---------------------------------------------------------------------------


def test_get_initial_lattice_guess_always_returns_a_value():
    """The initial guess for LAMMPS minimization is a separate concern.
    It must always return a usable float, independent of PG/REF data,
    and independent of the dev/prod environment gate.
    """
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        v = get_initial_lattice_guess("W-Ta", "BCC")
    assert isinstance(v, float)
    assert v > 0


def test_get_initial_lattice_guess_prefers_pg_when_available():
    pg_payload = {"value": 3.61, "unit": "angstrom", "source": "exp"}
    with patch(
        "autovc.reference.data.get_reference_value", return_value=pg_payload,
    ):
        v = get_initial_lattice_guess("Zr", "BCC")
    assert v == pytest.approx(3.61)


def test_get_initial_lattice_guess_falls_back_to_known_material():
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        v = get_initial_lattice_guess("U", "BCC")
    assert v == pytest.approx(LATTICE_GUESS["U"])


def test_get_initial_lattice_guess_returns_default_for_unknown():
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        v = get_initial_lattice_guess("W-Ta", "BCC")
    # Default guess — same as legacy _get_ref_value fallback default
    assert v == pytest.approx(3.4)


# ---------------------------------------------------------------------------
# Integration with _grade_property (BUG-20 reproduction guard)
# ---------------------------------------------------------------------------


def test_grade_property_with_missing_reference_returns_none():
    """Pin the existing _grade_property contract: reference=None → grade=None.
    This is the property that makes the missing-flag fix meaningful:
    callers can now propagate ReferenceLookup to _grade_property without
    the lattice_guess contaminating grades.
    """
    from autovc.runners.lammps_runner import _grade_property
    grade = _grade_property(3.181, None)
    assert grade["grade"] is None
    assert grade["absolute_error"] is None
    assert grade["relative_error"] is None


def test_grade_property_with_real_reference_grades_normally():
    from autovc.runners.lammps_runner import _grade_property
    # Real reference (e.g. Smirnov2014 U): 3.47 vs computed 3.181 → ~8.3% → D
    grade = _grade_property(3.181, 3.47)
    assert grade["grade"] in ("C", "D")
    assert grade["relative_error"] is not None


def test_bug20_w_ta_scenario_does_not_get_c_grade_from_guess():
    """Regression test for BUG-20: W-Ta with computed 3.181 must NOT receive
    a grade against the lattice_guess default of 3.4 (which would yield 'C').
    Instead, lookup_reference must return MISSING, so the grade is None.
    """
    from autovc.runners.lammps_runner import _grade_property

    # Simulate the prod lookup
    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        ref = lookup_reference("W-Ta", "BCC", "lattice_constant", env="production")

    # Caller must now skip grading when ref is not a real reference
    assert ref.is_real_reference is False
    grade = _grade_property(3.181, ref.value)
    assert grade["grade"] is None, (
        "BUG-20 regression: W-Ta received a grade computed against lattice_guess"
    )


def test_result_dict_includes_reference_flag_for_lattice():
    """The call-site output dict must propagate the flag, so the BFF /
    frontend can render ``reference_missing`` instead of a fake grade.
    """
    from autovc.runners.lammps_runner import _grade_property

    with patch(
        "autovc.reference.data.get_reference_value", return_value=None,
    ):
        ref = lookup_reference("W-Ta", "BCC", "lattice_constant", env="production")
    ref_v = ref.value if ref.is_real_reference else None
    g = _grade_property(3.181, ref_v)
    result = {
        "value": 3.181, "unit": "angstrom",
        "reference": ref_v, "reference_flag": ref.flag.value, **g,
    }
    assert result["reference"] is None
    assert result["reference_flag"] == "reference_missing"
    assert result["grade"] is None


def test_result_dict_includes_reference_ok_flag_when_pg_present():
    from autovc.runners.lammps_runner import _grade_property
    with patch(
        "autovc.reference.data.get_reference_value",
        return_value={"value": 3.47, "unit": "angstrom", "source": "Smirnov2014"},
    ):
        ref = lookup_reference("U", "BCC", "lattice_constant", env="production")
    ref_v = ref.value if ref.is_real_reference else None
    g = _grade_property(3.43, ref_v)  # ~1.2% off → A
    result = {
        "value": 3.43, "unit": "angstrom",
        "reference": ref_v, "reference_flag": ref.flag.value, **g,
    }
    assert result["reference"] == pytest.approx(3.47)
    assert result["reference_flag"] == "reference_ok"
    assert result["grade"] in ("A", "B")
