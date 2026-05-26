from autovc.core.calculator import KimCalculator

def test_calculator_init():
    calc = KimCalculator(kim_model="test_model")
    assert calc.kim_model == "test_model"
    assert hasattr(calc, "compute_energy")
    assert hasattr(calc, "compute_forces")
