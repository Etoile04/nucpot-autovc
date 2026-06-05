"""Tests for pair_style_compat module."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from autovc.pair_style_compat import (
    detect_lammps_version, get_mtp_pair_style_config, get_pair_style_config,
)
class TestVersionDetection:
    def test_detect_real_lammps(self):
        v = detect_lammps_version("/home/z203/nucpot-autovc/lmp_serial")
        assert v is not None
        assert v == (2022, 6, 23), f"Expected (2022,6,23), got {v}"
    def test_detect_auto(self):
        v = detect_lammps_version()
        assert v is not None
    def test_detect_bad_exec(self):
        assert detect_lammps_version("/nonexistent/lmp") is None

class TestMtpConfig:
    def test_old_lammps_generates_ini(self):
        cfg = get_mtp_pair_style_config((2022, 6, 23), "/path/to/pot.mtp")
        assert "mtp" in cfg["pair_style_line"]
        assert cfg["config_file"] is not None
        assert "pot.mtp" in cfg["pair_coeff_line"]
    def test_new_lammps_simple(self):
        cfg = get_mtp_pair_style_config((2025, 1, 15), "/path/to/pot.mtp")
        assert cfg["pair_style_line"] == "pair_style mtp"
        assert cfg["config_file"] is None
    def test_unknown_version_old_style(self):
        cfg = get_mtp_pair_style_config(None, "/path/to/pot.mtp")
        assert cfg["config_file"] is not None

class TestUnifiedConfig:
    def test_eam(self):
        cfg = get_pair_style_config("eam", "Cu_u3.eam")
        assert cfg["pair_style_line"] == "pair_style eam"
    def test_dp(self):
        cfg = get_pair_style_config("dp", "/models/dp.pb")
        assert "deepmd" in cfg["pair_style_line"]
    def test_tersoff(self):
        cfg = get_pair_style_config("tersoff", "Si.tersoff")
        assert "tersoff" in cfg["pair_style_line"]
    def test_unsupported_raises(self):
        try:
            get_pair_style_config("unknown", "f.dat")
            assert False
        except ValueError:
            pass
    def test_mtp_routes(self):
        cfg = get_pair_style_config("mtp", "pot.mtp", lammps_exec="/home/z203/nucpot-autovc/lmp_serial")
        assert "mtp" in cfg["pair_style_line"]
