"""Tests for the new Supabase + LAMMPS verification endpoints."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
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


def _mock_settings(url=""):
    """Create a mock settings object."""
    m = MagicMock()
    m.SUPABASE_URL = url
    return m


class TestVerifyEndpoint:
    """Test POST /api/verify and GET /api/verify/{job_id}."""

    @patch("autovc.config.get_settings", return_value=_mock_settings(""))
    def test_verify_no_supabase_url(self, mock_gs, client):
        """Should return 500 if SUPABASE_URL not configured."""
        r = client.post("/api/verify", json={"potential_id": "test-uuid", "template": "basic"})
        assert r.status_code == 500
        assert "SUPABASE_URL" in r.json()["detail"]

    @patch("autovc.config.get_settings", return_value=_mock_settings("https://test.supabase.co"))
    def test_verify_invalid_template(self, mock_gs, client):
        """Should return 400 for invalid template."""
        r = client.post("/api/verify", json={"potential_id": "test-uuid", "template": "invalid"})
        assert r.status_code == 400

    @patch("autovc.api.routes.create_verification", new_callable=AsyncMock)
    @patch("autovc.api.routes.get_potential", new_callable=AsyncMock)
    @patch("autovc.config.get_settings", return_value=_mock_settings("https://test.supabase.co"))
    def test_verify_creates_job(self, mock_settings, mock_get_potential, mock_create_verification, client):
        mock_get_potential.return_value = {
            "id": "test-uuid",
            "name": "U_EAM",
            "type": "EAM",
            "elements": ["U"],
            "lammps_config": {},
        }
        mock_create_verification.return_value = {"id": "job-123"}

        r = client.post("/api/verify", json={"potential_id": "test-uuid", "template": "basic"})
        assert r.status_code == 200
        data = r.json()
        assert data["job_id"] is not None
        assert data["status"] == "pending"
        assert data["estimated_seconds"] == 30

    @patch("autovc.api.routes.get_supabase_verification", new_callable=AsyncMock)
    def test_verify_status_not_found(self, mock_get, client):
        mock_get.return_value = None
        r = client.get("/api/verify/nonexistent-id")
        assert r.status_code == 404

    @patch("autovc.api.routes.get_supabase_verification", new_callable=AsyncMock)
    def test_verify_status_completed(self, mock_get, client):
        mock_get.return_value = {
            "id": "job-123",
            "status": "completed",
            "progress": 1.0,
            "current_step": "done",
            "results": {"lattice_constant": {"value": 2.85, "grade": "A"}},
            "overall_grade": "A",
            "template": "basic",
            "error_message": None,
            "created_at": "2026-01-01T00:00:00",
        }
        r = client.get("/api/verify/job-123")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "completed"
        assert data["overall_grade"] == "A"

    @patch("autovc.api.routes.get_potential", new_callable=AsyncMock)
    @patch("autovc.config.get_settings", return_value=_mock_settings("https://test.supabase.co"))
    def test_verify_potential_not_found(self, mock_settings, mock_get, client):
        mock_get.side_effect = ValueError("not found")
        r = client.post("/api/verify", json={"potential_id": "missing-uuid", "template": "basic"})
        assert r.status_code == 404


class TestLAMMPSRunner:
    """Test the LAMMPS runner module."""

    def test_grade_property(self):
        from autovc.runners.lammps_runner import _grade_property
        result = _grade_property(2.85, 2.85)
        assert result["grade"] == "A"
        assert result["relative_error"] == 0.0

    def test_grade_property_b(self):
        from autovc.runners.lammps_runner import _grade_property
        result = _grade_property(2.85 * 1.03, 2.85)  # 3% off
        assert result["grade"] == "B"

    def test_grade_property_f(self):
        from autovc.runners.lammps_runner import _grade_property
        result = _grade_property(2.85 * 1.25, 2.85)  # 25% off
        assert result["grade"] == "F"

    def test_grade_property_no_reference(self):
        from autovc.runners.lammps_runner import _grade_property
        result = _grade_property(3.0, None)
        assert result["grade"] is None

    def test_parse_lammps_output(self):
        from autovc.runners.lammps_runner import _parse_lammps_output
        output = """Total atoms: 128
RESULT lattice_constant 2.8563
RESULT cohesive_energy -5.491
some other output"""
        parsed = _parse_lammps_output(output)
        assert parsed["lattice_constant"] == pytest.approx(2.8563)
        assert parsed["cohesive_energy"] == pytest.approx(-5.491)

    def test_generate_lattice_input(self):
        from autovc.runners.lammps_runner import _generate_lattice_input
        script = _generate_lattice_input(
            ["U"], "pair_style eam/alloy", "pair_coeff * * U.eam.alloy U",
            guess_a=2.85, structure="bcc", size=4,
        )
        assert "pair_style eam/alloy" in script
        assert "pair_coeff * * U.eam.alloy U" in script
        assert "lattice bcc 2.85" in script
        assert "region box block 0 4 0 4 0 4" in script
        assert "RESULT lattice_constant" in script

    def test_generate_vacancy_input(self):
        from autovc.runners.lammps_runner import _generate_vacancy_input
        script = _generate_vacancy_input(
            ["U"], "pair_style eam/alloy", "pair_coeff * * U.eam.alloy U",
        )
        assert "delete_atoms atom 1" in script
        assert "vacancy_formation_energy" in script

    def test_runner_no_pot_file(self):
        """Runner should raise FileNotFoundError when no potential file exists."""
        from autovc.runners.lammps_runner import LAMMPSRunner
        runner = LAMMPSRunner(
            potential_meta={"name": "nonexistent", "elements": ["U"], "lammps_config": {}},
            potential_dir="/tmp/nonexistent_lammps_dir_12345",
        )
        import asyncio
        with pytest.raises(FileNotFoundError, match="缺少势函数文件"):
            asyncio.get_event_loop().run_until_complete(
                runner.run_property("lattice_constant")
            )
