"""KIM/ASE calculator wrapper for interatomic potentials.

Provides a thin wrapper around ASE's KIM calculator to compute
energy, forces, and stress for atomic configurations.

Requires:
    - kim-api C library (compiled from source)
    - kimpy (pip install)
    - ase (pip install)

The KIM models are loaded from ~/.local/lib/kim-api/ or the
KIM_REPOSITORY environment variable path.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class KimCalculator:
    """Wrapper around ASE KIM calculator for computing energy/forces/stress."""

    def __init__(self, kim_model: str):
        self.kim_model = kim_model
        self._calc = None

    def _get_calculator(self):
        """Lazy-load ASE KIM calculator."""
        if self._calc is None:
            # Ensure KIM API library is discoverable
            lib_path = os.path.expanduser("~/.local/lib")
            if lib_path not in os.environ.get("LD_LIBRARY_PATH", ""):
                os.environ["LD_LIBRARY_PATH"] = (
                    lib_path + ":" + os.environ.get("LD_LIBRARY_PATH", "")
                )
            try:
                from ase.calculators.kim import KIM
                self._calc = KIM(self.kim_model)
            except ImportError:
                raise RuntimeError(
                    "ASE KIM calculator not available. "
                    "Install: pip install ase kimpy && compile kim-api"
                )
            except Exception as e:
                raise RuntimeError(
                    f"Failed to initialize KIM model '{self.kim_model}': {e}"
                )
        return self._calc

    def compute_energy(self, atoms: Any) -> float:
        """Compute potential energy for an ASE Atoms object."""
        atoms.calc = self._get_calculator()
        return atoms.get_potential_energy()

    def compute_forces(self, atoms: Any) -> np.ndarray:
        """Compute forces for an ASE Atoms object."""
        atoms.calc = self._get_calculator()
        return atoms.get_forces()

    def compute_stress(self, atoms: Any) -> np.ndarray:
        """Compute stress tensor for an ASE Atoms object."""
        atoms.calc = self._get_calculator()
        return atoms.get_stress()
