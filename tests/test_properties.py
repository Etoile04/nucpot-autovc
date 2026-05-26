from autovc.core.properties import PropertyCalculator

def test_supported_properties():
    calc = PropertyCalculator()
    assert "lattice_constant" in calc.supported_properties()
    assert "cohesive_energy" in calc.supported_properties()
    assert "elastic_constants" in calc.supported_properties()

def test_lattice_interface():
    calc = PropertyCalculator()
    assert hasattr(calc, "compute_lattice_constant")

def test_cohesive_interface():
    calc = PropertyCalculator()
    assert hasattr(calc, "compute_cohesive_energy")
