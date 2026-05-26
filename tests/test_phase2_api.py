"""Tests for Phase 2 API endpoints: templates, v2 verification, reports."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from autovc.database import Base
import autovc.models  # noqa: F401
from autovc.main import create_app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    app = create_app(session_factory=TestSession)
    yield TestClient(app)


class TestTemplateEndpoints:
    def test_list_templates(self, client):
        r = client.get("/api/templates")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 4
        ids = {t["id"] for t in data}
        assert ids == {"basic", "mechanical", "defect", "comprehensive"}

    def test_get_template_detail(self, client):
        r = client.get("/api/templates/basic")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "basic"
        assert "lattice_constant" in data["properties"]

    def test_get_template_not_found(self, client):
        r = client.get("/api/templates/nonexistent")
        assert r.status_code == 404


class TestVerificationV2:
    def _create_potential(self, client, name="test_pot"):
        return client.post("/api/potentials", json={
            "name": name,
            "potential_type": "EAM",
            "species": ["U"],
        }).json()

    def test_submit_v2_basic_template(self, client):
        self._create_potential(client)
        r = client.post("/api/verification/v2", json={
            "potential_name": "test_pot",
            "template": "basic",
        })
        assert r.status_code == 202
        data = r.json()
        assert set(data["properties_requested"]) == {"lattice_constant", "cohesive_energy"}

    def test_submit_v2_with_overrides(self, client):
        self._create_potential(client, "test_pot2")
        r = client.post("/api/verification/v2", json={
            "potential_name": "test_pot2",
            "template": "basic",
            "property_overrides": ["bulk_modulus", "vacancy_formation_energy"],
        })
        assert r.status_code == 202
        data = r.json()
        assert data["properties_requested"] == ["bulk_modulus", "vacancy_formation_energy"]

    def test_submit_v2_bad_template(self, client):
        self._create_potential(client, "test_pot3")
        r = client.post("/api/verification/v2", json={
            "potential_name": "test_pot3",
            "template": "nonexistent",
        })
        assert r.status_code == 400

    def test_submit_v2_potential_not_found(self, client):
        r = client.post("/api/verification/v2", json={
            "potential_name": "missing",
            "template": "basic",
        })
        assert r.status_code == 404

    def test_submit_v2_comprehensive_template(self, client):
        self._create_potential(client, "test_comp")
        r = client.post("/api/verification/v2", json={
            "potential_name": "test_comp",
            "template": "comprehensive",
        })
        assert r.status_code == 202
        data = r.json()
        assert len(data["properties_requested"]) == 5

    def test_v2_schema_parameter_overrides(self, client):
        self._create_potential(client, "test_params")
        r = client.post("/api/verification/v2", json={
            "potential_name": "test_params",
            "template": "basic",
            "parameter_overrides": {"lattice_guess": 3.5},
        })
        assert r.status_code == 202


class TestVerificationReport:
    def test_report_not_found(self, client):
        r = client.get("/api/verification/999/report")
        assert r.status_code == 404

    def test_report_pending_job(self, client):
        client.post("/api/potentials", json={
            "name": "rpt_pot", "potential_type": "EAM", "species": ["U"],
        })
        job = client.post("/api/verification", json={
            "potential_name": "rpt_pot",
            "properties": ["lattice_constant"],
        }).json()

        r = client.get(f"/api/verification/{job['id']}/report")
        assert r.status_code == 200
        data = r.json()
        assert data["job_id"] == job["id"]
        assert data["overall_grade"] is None
        assert data["property_scores"] == []

    def test_report_structure(self, client):
        client.post("/api/potentials", json={
            "name": "rpt_pot2", "potential_type": "EAM", "species": ["U"],
        })
        job = client.post("/api/verification", json={
            "potential_name": "rpt_pot2",
            "properties": ["lattice_constant", "cohesive_energy"],
        }).json()

        r = client.get(f"/api/verification/{job['id']}/report")
        data = r.json()
        assert "job_id" in data
        assert "potential_name" in data
        assert "overall_grade" in data
        assert "property_scores" in data
        assert "summary" in data
