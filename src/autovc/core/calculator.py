import logging
import numpy as np

logger = logging.getLogger(__name__)

class KimCalculator:
    def __init__(self, kim_model: str):
        self.kim_model = kim_model
        self._calc = None

    def _get_calculator(self):
        if self._calc is None:
            try:
                import kimpy
                self._calc = kimpy.calculator.KIMCalculator(self.kim_model)
            except ImportError:
                raise RuntimeError("kimpy not installed")
            except Exception as e:
                raise RuntimeError(f"KIM model init failed: {e}")
        return self._calc

    def compute_energy(self, atoms):
        atoms.calc = self._get_calculator()
        return atoms.get_potential_energy()

    def compute_forces(self, atoms):
        atoms.calc = self._get_calculator()
        return atoms.get_forces()
