from autovc.schemas import VerificationRequest, PotentialCreate

def test_verification_request_defaults():
    req = VerificationRequest(potential_name="test")
    assert req.properties == ["lattice_constant", "cohesive_energy", "elastic_constants"]
    assert req.structure == "BCC"

def test_potential_create():
    pc = PotentialCreate(name="test", potential_type="EAM", species=["U"])
    assert pc.name == "test"
