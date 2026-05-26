from autovc.reference.data import get_reference_value, list_available_properties, list_available_materials

def test_list_properties():
    assert "lattice_constant" in list_available_properties()
    assert "cohesive_energy" in list_available_properties()

def test_list_materials():
    mats = list_available_materials()
    assert "U" in mats
    assert "U-Mo" in mats

def test_get_reference():
    ref = get_reference_value("U", "BCC_gamma", "lattice_constant")
    assert ref is not None
    assert ref["value"] > 0

def test_get_missing():
    assert get_reference_value("XXX", "BCC", "lattice_constant") is None
