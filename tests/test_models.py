import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from autovc.database import Base
from autovc.models import Potential, VerificationJob, VerificationResult

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_create_potential(db_session):
    pot = Potential(name="EAM_U_test", potential_type="EAM", species=["U", "Mo"], kim_model_id="EAM_test")
    db_session.add(pot)
    db_session.commit()
    assert pot.id is not None
    assert pot.species == ["U", "Mo"]

def test_create_verification_job(db_session):
    pot = Potential(name="test", potential_type="EAM", species=["U"])
    db_session.add(pot)
    db_session.flush()
    job = VerificationJob(potential_id=pot.id, status="pending", properties_requested=["lattice_constant"])
    db_session.add(job)
    db_session.commit()
    assert job.status == "pending"

def test_create_verification_result(db_session):
    pot = Potential(name="test", potential_type="EAM", species=["U"])
    db_session.add(pot)
    db_session.flush()
    job = VerificationJob(potential_id=pot.id, status="completed", properties_requested=["lattice_constant"])
    db_session.add(job)
    db_session.flush()
    result = VerificationResult(job_id=job.id, property_name="lattice_constant", computed_value=3.42, reference_value=3.38, unit="angstrom", relative_error=0.0118, grade="A")
    db_session.add(result)
    db_session.commit()
    assert result.grade == "A"
