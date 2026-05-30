import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from autovc.database import Base
from autovc.models import Potential, VerificationJob, VerificationResult
import autovc.models  # noqa: F401 — register tables with Base.metadata
from autovc.main import create_app

@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Potential.__table__.create(engine, checkfirst=True)
    VerificationJob.__table__.create(engine, checkfirst=True)
    VerificationResult.__table__.create(engine, checkfirst=True)
    TestSession = sessionmaker(bind=engine)
    app = create_app(session_factory=TestSession)
    return TestClient(app)

def test_health(client):
    assert client.get("/api/health").status_code == 200

def test_create_potential(client):
    r = client.post("/api/potentials", json={"name":"EAM_U","potential_type":"EAM","species":["U"]})
    assert r.status_code == 201
    assert r.json()["name"] == "EAM_U"

def test_list_potentials(client):
    client.post("/api/potentials", json={"name":"p1","potential_type":"EAM","species":["U"]})
    r = client.get("/api/potentials")
    assert r.status_code == 200 and len(r.json()) >= 1

def test_get_potential_404(client):
    assert client.get("/api/potentials/999").status_code == 404

def test_submit_verification(client):
    client.post("/api/potentials", json={"name":"EAM_V","potential_type":"EAM","species":["U"],"kim_model_id":"test_kim"})
    r = client.post("/api/verification", json={"potential_name":"EAM_V","properties":["lattice_constant"]})
    assert r.status_code == 202
    assert r.json()["status"] == "pending"

def test_get_verification(client):
    client.post("/api/potentials", json={"name":"EAM_S","potential_type":"EAM","species":["U"]})
    jr = client.post("/api/verification", json={"potential_name":"EAM_S","properties":["lattice_constant"]})
    jid = jr.json()["id"]
    r = client.get(f"/api/verification/{jid}")
    assert r.status_code == 200
