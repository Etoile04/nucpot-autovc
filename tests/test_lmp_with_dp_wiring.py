"""NFM-5281 — lmp-with-dp wiring guards (build/install lane).

The deepmd pair style needs (a) an LAMMPS binary built with the PLUGIN
package — Debian trixie's ``lammps`` 20250204 ships WITHOUT the ``plugin``
command (verified in-container 2026-10-08: "Unknown command: plugin load"),
and (b) the staged runtime libs on LD_LIBRARY_PATH=/opt/deepmd/lib when
that binary runs. These tests pin the shipped wiring:

* ``bin/lmp-plugin`` — vendored linux/aarch64 LAMMPS (same generation as
  Debian's 20250204, tag patch_4Feb2025) built with PKG_PLUGIN + KSPACE
  (the plugin's KSpace typeinfo comes from the host binary) + MANYBODY +
  MOLECULE. Reproducible via ``bin/build-lmp-plugin.sh``.
* ``bin/lmp-with-dp`` — the wrapper LAMMPSRunner dispatches to: exports
  LD_LIBRARY_PATH=/opt/deepmd/lib (the compose bind mount) and execs
  lmp-plugin, forwarding arguments verbatim.
* Dockerfile — installs the wrapper where the runner expects it
  (/usr/local/bin/lmp-with-dp).
"""

import os
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPO_ROOT / "bin" / "lmp-with-dp"
BUILD_SCRIPT = REPO_ROOT / "bin" / "build-lmp-plugin.sh"
DOCKERFILE = REPO_ROOT / "Dockerfile"


def _is_executable(path: Path) -> bool:
    return path.is_file() and bool(path.stat().st_mode & stat.S_IXUSR)


class TestLmpWithDpWrapper:
    def test_wrapper_exists_and_is_executable(self):
        assert _is_executable(WRAPPER), "bin/lmp-with-dp must be committed +x"

    def test_wrapper_sets_deepmd_library_path_and_execs_plugin_binary(self):
        text = WRAPPER.read_text(encoding="utf-8")
        assert "/opt/deepmd/lib" in text, (
            "wrapper must export LD_LIBRARY_PATH=/opt/deepmd/lib — the "
            "compose bind mount is the only source of the staged runtime"
        )
        assert "lmp-plugin" in text, "wrapper must exec the PLUGIN-capable binary"
        assert "exec" in text, "wrapper must exec (not fork) so signals/PID semantics hold"

    def test_build_script_documents_reproducible_provenance(self):
        assert _is_executable(BUILD_SCRIPT)
        text = BUILD_SCRIPT.read_text(encoding="utf-8")
        assert "patch_4Feb2025" in text, "must pin the LAMMPS tag Debian 20250204 maps to"
        for pkg in ("PKG_PLUGIN", "PKG_KSPACE", "PKG_MANYBODY", "PKG_MOLECULE"):
            assert pkg in text, f"build script must enable {pkg}"


class TestDockerfileWiring:
    def test_dockerfile_installs_wrapper_at_runner_default(self):
        text = DOCKERFILE.read_text(encoding="utf-8")
        assert "lmp-with-dp" in text, (
            "runtime stage must expose the wrapper at /usr/local/bin/lmp-with-dp "
            "(LAMMPSRunner's default DP binary)"
        )
        assert "lmp-plugin" in text or "bin/lmp" in text, (
            "the PLUGIN-capable binary must ship in the image"
        )
