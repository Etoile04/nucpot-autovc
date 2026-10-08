"""NFM-5281 — DeepMD re-enablement guards for the LAMMPS runner.

The DP path was hard-disabled (``ValueError`` in ``LAMMPSRunner.__init__``)
while the deepmd-plugin bind source was an empty husk (NFM-5271). The SRE
lane repopulated and in-container verified the runtime set
(deploy-host record ``deepmd-plugin/MANIFEST.md`` — the docker-compose bind
source for /opt/deepmd/lib, not versioned in this repo — 2026-10-03:
deepmd-kit 3.2.0 + TF 2.18.1 + torch 2.10.0, linux/aarch64, dlopen-clean),
so the runner must accept DP
potentials again — and the input generators must emit a loadable plugin
line. Three latent defects shipped with the original DP code and are
pinned here:

* the plugin line pointed at ``libdeepmd_lmpplugin.son`` (typo — the
  staged file is ``.so``);
* the lattice template interpolated ``{plugin_load}{pair_style}`` with no
  separator, so a DP script concatenated two LAMMPS commands onto one line;
* the elastic generator computed ``plugin_load`` but never emitted it (and
  only on the non-hcp branch), so DP elastic jobs would die at
  ``pair_style deepmd`` with the plugin never loaded.

The staged plugin lib resolves LAMMPS core symbols from the host ``lmp``
process, so the load must happen inside the same LAMMPS run that uses the
``deepmd`` pair style — one ``plugin load`` per input script, before the
first physics block (LAMMPS ``clear`` does not unload plugins).
"""

from unittest.mock import MagicMock, patch

from autovc.runners.lammps_runner import (
    LAMMPSRunner,
    _generate_basic_input,
    _generate_elastic_input,
    _generate_lattice_input,
    _generate_strained_input,
    _generate_surface_energy_input,
    _generate_vacancy_input,
)

PLUGIN_LINE = "plugin load /opt/deepmd/lib/libdeepmd_lmpplugin.so"
DP_META = {"name": "FeHHe-DP", "type": "DP", "elements": ["Fe", "H", "He"]}
PAIR_STYLE = "pair_style deepmd /uploads/FeHHe-DP.pb"
PAIR_COEFF = "pair_coeff * * /uploads/FeHHe-DP.pb"


def _settings(**attrs):
    mock = MagicMock()
    for key, value in attrs.items():
        setattr(mock, key, value)
    return mock


def _make_runner(meta=None, **kwargs):
    with patch(
        "autovc.runners.lammps_runner.get_settings",
        return_value=_settings(LAMMPS_BIN="lmp_from_settings"),
    ):
        return LAMMPSRunner(meta or DP_META, **kwargs)


class TestRunnerAcceptsDP:
    """LAMMPSRunner must construct for DP potentials (NFM-5281)."""

    def test_dp_meta_no_longer_raises_and_selects_lmp_with_dp(self):
        runner = _make_runner()
        assert runner._is_dp is True
        assert runner._is_meam is False
        assert runner.lammps_bin == "/usr/local/bin/lmp-with-dp"

    def test_deepmd_spelling_and_case_also_match(self):
        for ptype in ("DeepMD", "deepmd", "dp", "DEEPMD"):
            runner = _make_runner({"name": "X", "type": ptype, "elements": ["Fe"]})
            assert runner._is_dp is True, ptype
            assert runner.lammps_bin == "/usr/local/bin/lmp-with-dp"

    def test_explicit_lammps_bin_wins_for_dp(self):
        runner = _make_runner(lammps_bin="/opt/lmp-custom")
        assert runner.lammps_bin == "/opt/lmp-custom"

    def test_env_override_for_dp_binary(self, monkeypatch):
        monkeypatch.setenv("LAMMPS_BIN_DP", "/env/lmp-with-dp")
        runner = _make_runner()
        assert runner.lammps_bin == "/env/lmp-with-dp"

    def test_dp_runner_gets_potential_dir(self):
        """The DP branch must resolve potential files like every other
        type — potential_dir was previously only set on the classical
        branch, leaving _resolve_pot_file to AttributeError."""
        runner = _make_runner()
        assert runner.potential_dir
        assert "uploads" in runner.potential_dir

    def test_meam_runner_gets_potential_dir(self):
        runner = _make_runner(
            {"name": "X", "type": "MEAM", "elements": ["U"]},
        )
        assert runner.potential_dir

    def test_non_dp_selection_unchanged(self):
        runner = _make_runner({"name": "U_EAM", "type": "EAM", "elements": ["U"]})
        assert runner._is_dp is False
        assert runner.lammps_bin == "lmp_from_settings"


class TestLatticeInputPluginLine:
    """_generate_lattice_input must emit a loadable, own-line plugin load."""

    def test_plugin_line_is_own_line_with_so_extension(self):
        script = _generate_lattice_input(
            ["Fe"], PAIR_STYLE, PAIR_COEFF, structure="bcc", is_dp=True
        )
        assert PLUGIN_LINE in script
        assert ".son" not in script
        # The plugin command must occupy its own line, not concatenate with
        # pair_style (the old {plugin_load}{pair_style} template fused them).
        lines = script.splitlines()
        plugin_idx = lines.index(PLUGIN_LINE)
        pair_idx = next(i for i, ln in enumerate(lines) if ln.startswith("pair_style"))
        assert pair_idx == plugin_idx + 1

    def test_classical_input_has_no_plugin_line(self):
        script = _generate_lattice_input(
            ["U"], "pair_style eam/fs", "pair_coeff * * U.eam.fs", structure="bcc"
        )
        assert "plugin load" not in script
        assert ".son" not in script


class TestElasticInputPluginLine:
    """_generate_elastic_input must emit the plugin load it computes."""

    def test_plugin_line_emitted_once_before_first_physics(self):
        script = _generate_elastic_input(
            ["Fe"], PAIR_STYLE, PAIR_COEFF, is_dp=True, structure="bcc"
        )
        assert PLUGIN_LINE in script
        assert ".son" not in script
        assert script.count(PLUGIN_LINE) == 1, "plugin load must appear once per run"
        first_pair = script.index("pair_style")
        assert script.index(PLUGIN_LINE) < first_pair, (
            "plugin load must precede the first pair_style — the deepmd "
            "pair_style resolves its symbols from the loaded plugin"
        )

    def test_hcp_dp_keeps_plugin_line(self):
        """The old code computed plugin_load only on the non-hcp branch."""
        script = _generate_elastic_input(
            ["Fe"], PAIR_STYLE, PAIR_COEFF, is_dp=True, structure="hcp"
        )
        assert PLUGIN_LINE in script
        assert script.index(PLUGIN_LINE) < script.index("pair_style")

    def test_classical_elastic_has_no_plugin_line(self):
        script = _generate_elastic_input(
            ["U"], "pair_style eam/fs", "pair_coeff * * U.eam.fs", structure="bcc"
        )
        assert "plugin load" not in script


class TestRunnerPathGeneratorsPluginLine:
    """Every generator run_property actually dispatches to must emit the
    plugin load for DP — elastic_constants goes through _generate_basic_input
    and _generate_strained_input (not _generate_elastic_input), vacancy and
    surface_energy have their own generators. A missing plugin line kills
    the run at `pair_style deepmd` ("unrecognized pair style")."""

    def test_basic_input_plugin_line_precedes_pair_style(self):
        script = _generate_basic_input(
            ["Fe"], PAIR_STYLE, PAIR_COEFF, 3.0, "bcc", size=3, is_dp=True
        )
        lines = script.splitlines()
        plugin_idx = lines.index(PLUGIN_LINE)
        pair_idx = next(i for i, ln in enumerate(lines) if ln.startswith("pair_style"))
        assert pair_idx == plugin_idx + 1

    def test_strained_input_plugin_line_precedes_pair_style(self):
        script = _generate_strained_input(
            ["Fe"], PAIR_STYLE, PAIR_COEFF, 3.0, "bcc", size=3,
            strain_x=0.001, is_dp=True
        )
        lines = script.splitlines()
        plugin_idx = lines.index(PLUGIN_LINE)
        pair_idx = next(i for i, ln in enumerate(lines) if ln.startswith("pair_style"))
        assert pair_idx == plugin_idx + 1

    def test_strained_shear_input_keeps_plugin_line(self):
        script = _generate_strained_input(
            ["Fe"], PAIR_STYLE, PAIR_COEFF, 3.0, "bcc", size=3,
            shear_xy=0.001, is_dp=True
        )
        assert PLUGIN_LINE in script

    def test_vacancy_input_accepts_is_dp_and_emits_plugin_line(self):
        script = _generate_vacancy_input(
            ["Fe"], PAIR_STYLE, PAIR_COEFF, 3.0, "bcc", size=3, is_dp=True
        )
        lines = script.splitlines()
        plugin_idx = lines.index(PLUGIN_LINE)
        pair_idx = next(i for i, ln in enumerate(lines) if ln.startswith("pair_style"))
        assert pair_idx == plugin_idx + 1

    def test_vacancy_input_without_is_dp_still_constructs(self):
        script = _generate_vacancy_input(
            ["U"], "pair_style eam/fs", "pair_coeff * * U.eam.fs", 3.4, "bcc"
        )
        assert "plugin load" not in script
        assert "vacancy_formation_energy" in script

    def test_surface_input_plugin_line_precedes_pair_style(self):
        script = _generate_surface_energy_input(
            ["Fe"], PAIR_STYLE, PAIR_COEFF, 3.0, "bcc", size=4, is_dp=True
        )
        lines = script.splitlines()
        plugin_idx = lines.index(PLUGIN_LINE)
        pair_idx = next(i for i, ln in enumerate(lines) if ln.startswith("pair_style"))
        assert pair_idx == plugin_idx + 1

    def test_classical_runner_path_inputs_have_no_plugin_line(self):
        for script in (
            _generate_basic_input(
                ["U"], "pair_style eam/alloy", "pair_coeff * * U.eam.alloy U",
                3.4, "bcc", size=3
            ),
            _generate_strained_input(
                ["U"], "pair_style eam/alloy", "pair_coeff * * U.eam.alloy U",
                3.4, "bcc", size=3, strain_x=0.001
            ),
            _generate_vacancy_input(
                ["U"], "pair_style eam/alloy", "pair_coeff * * U.eam.alloy U",
                3.4, "bcc"
            ),
            _generate_surface_energy_input(
                ["U"], "pair_style eam/alloy", "pair_coeff * * U.eam.alloy U",
                3.4, "bcc"
            ),
        ):
            assert "plugin load" not in script
