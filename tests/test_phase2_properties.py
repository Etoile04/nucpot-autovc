"""Tests for Phase 2 enhanced property calculations."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import numpy as np
from autovc.core.properties import PropertyCalculator


@pytest.fixture
def calc():
    return PropertyCalculator()


class TestBulkModulus:
    def test_bulk_modulus_from_elastic_constants(self, calc):
        """Test B = (C11 + 2*C12) / 3 derivation."""
        elastic_result = {"C11": 463.0, "C12": 161.0, "C44": 109.0}
        result = calc.compute_bulk_modulus(method="elastic", elastic_result=elastic_result)
        assert result["property"] == "bulk_modulus"
        assert result["method"] == "elastic_constants"
        expected = (463.0 + 2 * 161.0) / 3.0
        assert abs(result["value"] - expected) < 0.01

    def test_bulk_modulus_elastic_missing_c11(self, calc):
        """If C11 is missing, falls back to ev_curve."""
        elastic_result = {"C12": 161.0}
        with patch.object(calc, 'compute_elastic_constants') as mock_ec:
            mock_ec.return_value = {
                "value": {"C11": None, "C12": None, "C44": None, "bulk_modulus": 262.0},
                "unit": "GPa",
                "property": "elastic_constants",
            }
            result = calc.compute_bulk_modulus(method="elastic", elastic_result=elastic_result)
            assert result["value"] == 262.0
            assert result["method"] == "ev_curve"

    def test_bulk_modulus_mo_reference(self, calc):
        """Test with Mo reference values: C11=463, C12=161 → B≈261.67 GPa."""
        result = calc.compute_bulk_modulus(
            method="elastic",
            elastic_result={"C11": 463.0, "C12": 161.0, "C44": 109.0},
        )
        assert abs(result["value"] - 261.67) < 0.1

    def test_bulk_modulus_default_method(self, calc):
        """Default method should use EV curve."""
        with patch.object(calc, 'compute_elastic_constants') as mock_ec:
            mock_ec.return_value = {
                "value": {"C11": None, "C12": None, "C44": None, "bulk_modulus": 150.0},
                "unit": "GPa",
                "property": "elastic_constants",
            }
            result = calc.compute_bulk_modulus(calculator=MagicMock())
            assert result["method"] == "ev_curve"
            assert result["value"] == 150.0


class TestVacancyFormationEnergy:
    def test_vacancy_formula(self):
        """Test the vacancy formation energy formula directly:
        Evf = E_vac - (N-1)/N * E_perfect
        """
        N = 27  # 3x3x3 BCC
        e_perfect = -135.0  # -5 eV/atom * 27
        e_vac = -131.0  # slightly less stable
        evf = e_vac - (N - 1) / N * e_perfect
        # evf = -131 - (26/27)*(-135) = -131 + 130 = -1.0
        assert abs(evf - (-1.0)) < 0.01

    def test_vacancy_supercell_field(self, calc):
        """Verify supercell_size field in result when using mock."""
        mock_calc = MagicMock()
        # Mock the bulk() call to return a fake atoms object
        mock_atoms = MagicMock()
        mock_atoms.get_potential_energy = MagicMock(return_value=-100.0)
        mock_atoms.__len__ = MagicMock(return_value=8)
        # When multiplied by supercell
        mock_supercell = MagicMock()
        mock_supercell.get_potential_energy = MagicMock(return_value=-800.0)
        mock_supercell.__len__ = MagicMock(return_value=64)  # 8 * 2^3
        mock_supercell.copy = MagicMock()

        mock_vac = MagicMock()
        mock_vac.get_potential_energy = MagicMock(return_value=-790.0)
        mock_vac.__len__ = MagicMock(return_value=63)
        mock_supercell.copy.return_value = mock_vac

        mock_atoms.__mul__ = MagicMock(return_value=mock_supercell)

        with patch('autovc.core.properties.bulk', return_value=mock_atoms):
            result = calc.compute_vacancy_formation_energy(
                calculator=mock_calc, species="U", structure="BCC",
                lattice_guess=3.4, supercell_size=2,
            )
            assert result["property"] == "vacancy_formation_energy"
            assert result["unit"] == "eV"
            assert "supercell_size" in result
            # 64 - 1 = 63 atoms, Evf = -790 - (63/64)*(-800) = -790 + 787.5 = -2.5
            evf = -790.0 - (63 / 64) * (-800.0)
            assert abs(result["value"] - round(evf, 4)) < 0.01


class TestPropertyDefs:
    def test_bulk_modulus_in_defs(self, calc):
        info = calc.get_property_info("bulk_modulus")
        assert info["unit"] == "GPa"

    def test_vacancy_in_defs(self, calc):
        info = calc.get_property_info("vacancy_formation_energy")
        assert info["unit"] == "eV"

    def test_supported_properties_count(self, calc):
        props = calc.supported_properties()
        assert len(props) == 5
        assert "bulk_modulus" in props
        assert "vacancy_formation_energy" in props
