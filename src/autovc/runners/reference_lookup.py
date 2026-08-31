"""Reference value lookup with explicit semantics (NFM-3873 / BUG-20).

Replaces the legacy ``_get_ref_value`` helper that returned ``float | None``
and silently substituted a hardcoded ``lattice_guess`` (default 3.4 Å)
when PG / ``_FALLBACK`` had no entry. Callers grading results then
computed grades against an *optimization initial guess* — producing the
W-Ta "reference=3.4, grade=C" misfire documented in BUG-20.

New contract
------------

``lookup_reference(material, structure, prop)`` returns a
:class:`ReferenceLookup` whose ``flag`` distinguishes:

* ``REFERENCE_OK`` — a real reference value (PG hit). Usable for grading.
* ``DEV_FALLBACK`` — the lattice fallback table fired (dev environment
  only). **NOT** a real reference; callers must not use it for grading.
* ``REFERENCE_MISSING`` — no PG / fallback value available. Callers must
  not grade; record ``reference_missing`` and skip.

Production environments never use the lattice fallback. The env gate
defaults to "production" when neither ``NUCPOT_ENV`` nor ``NFM_ENV`` is
set, so the safe default is *no* silent fallback.

``get_initial_lattice_guess`` is the separate API for the LAMMPS
initial-guess path (``run_property`` line ~792) where the goal is to
start minimization from a sensible value, not to grade anything.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fallback table — DEV ONLY
# ---------------------------------------------------------------------------

# Default lattice constant guesses for a small set of common metallic
# systems. These values are *initial guesses for LAMMPS box minimization*,
# NOT reference values for grading. They are only consulted when
# ``lookup_reference`` runs in a dev environment AND the lookup misses
# PG and the autovc ``_FALLBACK`` table. Production runs never see them.
LATTICE_GUESS: dict[str, float] = {
    "U": 2.85,
    "Mo": 3.15,
    "Zr": 3.61,
    "U-Mo": 3.40,
    "U-Zr": 3.45,
}
_DEFAULT_LATTICE_GUESS = 3.4


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

_DEV_ENV_NAMES = frozenset({"dev", "development", "local", "test"})


def _normalize_env(env: str | None) -> str:
    return (env or "").strip().lower()


def _resolve_env(env: str | None) -> str:
    """Return the env name to use, honouring explicit override then env vars.

    Lookup order: explicit ``env`` argument → ``NUCPOT_ENV`` → ``NFM_ENV``.
    Default to ``"production"`` when none is set, so the safe default is
    *no* silent fallback.
    """
    if env is not None:
        return _normalize_env(env)
    for var in ("NUCPOT_ENV", "NFM_ENV"):
        val = os.environ.get(var)
        if val:
            return _normalize_env(val)
    return "production"


def _is_dev_environment(env: str | None) -> bool:
    return _resolve_env(env) in _DEV_ENV_NAMES


# ---------------------------------------------------------------------------
# Typed result
# ---------------------------------------------------------------------------

class ReferenceFlag(str, Enum):
    """Provenance flag for a :class:`ReferenceLookup`.

    Using ``str, Enum`` so the value serialises cleanly to JSON and
    matches the issue contract (``flag: reference_missing``).
    """

    REFERENCE_OK = "reference_ok"
    REFERENCE_MISSING = "reference_missing"
    DEV_FALLBACK = "dev_fallback"


@dataclass(frozen=True)
class ReferenceLookup:
    """Result of a reference value lookup with explicit semantics.

    ``value`` is ``None`` whenever ``flag`` is ``REFERENCE_MISSING``.
    Callers must use :attr:`is_real_reference` to decide whether to
    grade; a dev fallback is intentionally NOT a real reference even
    though ``value`` is populated.
    """

    value: float | None
    flag: ReferenceFlag

    @property
    def is_real_reference(self) -> bool:
        """``True`` iff this is a real reference usable for grading."""
        return self.flag is ReferenceFlag.REFERENCE_OK


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Properties whose miss may be served by the dev lattice fallback table.
# Other properties (cohesive_energy, C11, C12, C44, vacancy, surface, ...)
# never get a fallback — they return MISSING directly.
_LATTICE_FALLBACK_PROPS = frozenset({"lattice_constant"})


def _query_reference_data(
    material: str, structure: str, prop: str,
) -> dict[str, Any] | None:
    """Query the autovc.reference.data PG / _FALLBACK table.

    Import is deferred to keep this module usable in unit tests that
    don't have DATABASE_URL set.
    """
    try:
        from autovc.reference.data import get_reference_value
    except ImportError as exc:
        logger.debug("autovc.reference.data unavailable: %s", exc)
        return None
    try:
        result = get_reference_value(material, structure, prop)
    except Exception as exc:  # noqa: BLE001 — narrow in caller
        logger.debug(
            "get_reference_value failed for %s/%s/%s: %s",
            material, structure, prop, exc,
        )
        return None
    if not isinstance(result, dict):
        return None
    raw = result.get("value")
    if raw is None:
        return None
    try:
        return {**result, "value": float(raw)}
    except (TypeError, ValueError):
        return None


def lookup_reference(
    material: str,
    structure: str,
    prop: str,
    *,
    env: str | None = None,
) -> ReferenceLookup:
    """Look up a reference value with explicit provenance.

    Returns a :class:`ReferenceLookup` whose :attr:`~ReferenceLookup.flag`
    tells the caller whether ``value`` is a real reference (usable for
    grading), a dev-only fallback (NOT usable for grading), or a miss.

    The lattice fallback table only fires in dev-like environments
    (``dev`` / ``development`` / ``local`` / ``test``). Production
    environments always return ``REFERENCE_MISSING`` on PG / REF miss,
    so prod never silently substitutes a guess for a reference.
    """
    result = _query_reference_data(material, structure, prop)
    if result is not None:
        return ReferenceLookup(
            value=result["value"],
            flag=ReferenceFlag.REFERENCE_OK,
        )

    # No PG / REF data. Decide whether the dev fallback table applies.
    if prop in _LATTICE_FALLBACK_PROPS and _is_dev_environment(env):
        guess = LATTICE_GUESS.get(material, _DEFAULT_LATTICE_GUESS)
        logger.debug(
            "DEV fallback for lattice_constant %s/%s → %.3f",
            material, structure, guess,
        )
        return ReferenceLookup(
            value=float(guess),
            flag=ReferenceFlag.DEV_FALLBACK,
        )

    return ReferenceLookup(value=None, flag=ReferenceFlag.REFERENCE_MISSING)


def get_initial_lattice_guess(
    material: str,
    structure: str,
    *,
    env: str | None = None,
) -> float:
    """Return a usable initial guess for the LAMMPS box minimization.

    This is a *separate* code path from :func:`lookup_reference`. The
    initial guess is purely a starting point for relaxation; it is
    never compared against the computed value for grading.

    Preference order:

    1. PG / ``_FALLBACK`` reference value when present (env-independent).
    2. The hardcoded :data:`LATTICE_GUESS` for known materials.
    3. :data:`_DEFAULT_LATTICE_GUESS` (3.4 Å) for unknown materials.
    """
    result = _query_reference_data(material, structure, "lattice_constant")
    if result is not None:
        return float(result["value"])
    if _is_dev_environment(env):
        return LATTICE_GUESS.get(material, _DEFAULT_LATTICE_GUESS)
    # Outside dev, still need a starting value for LAMMPS — but make it
    # explicit this is a guess, not a reference.
    return LATTICE_GUESS.get(material, _DEFAULT_LATTICE_GUESS)
