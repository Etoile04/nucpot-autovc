"""NFM-5281 — behavioral guards for the lmp-with-dp wiring.

The deepmd pair style needs (a) an LAMMPS binary/library whose Pair vtable
and MPI ABI match the plugin .so, and (b) the staged runtime libs on
LD_LIBRARY_PATH=/opt/deepmd/lib when that binary runs. These tests
exercise the shipped wiring rather than grep its sources:

* ``bin/lmp-with-dp`` — executed against a stub plugin binary (via the
  wrapper's LMP_PLUGIN_BIN override) to prove it exports
  LD_LIBRARY_PATH=/opt/deepmd/lib, forwards argv verbatim, and execs (not
  forks) so PID/signal/exit-code semantics belong to LAMMPS. With no
  override it targets /usr/local/bin/lmp-plugin, where the Dockerfile
  runtime stage installs the launcher.
* ``bin/lmp-plugin-launcher.c`` — compiled against a stub implementation
  of the stable LAMMPS C API and run, asserting lmp(1) CLI semantics:
  the last ``-in`` wins, no ``-in`` reads stdin, and the library is
  opened/closed through lammps_open_no_mpi/lammps_close.
* ``Dockerfile`` — parsed into a semantic stage model (stages, RUN
  commands, COPY directives) to assert the deepmd-CI lammps wheel pin
  (==2025.7.22.2.0, stable_22Jul2025_update2, MPICH ABI) lives in the
  lmp-builder stage's pip install, the launcher is compiled there against
  the wheel's liblammps.so, and the runtime stage ships the launcher,
  the library, the MPICH runtime and the lmp-with-dp symlink.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPO_ROOT / "bin" / "lmp-with-dp"
LAUNCHER = REPO_ROOT / "bin" / "lmp-plugin-launcher.c"
DOCKERFILE = REPO_ROOT / "Dockerfile"
LAMMPS_WHEEL_PIN = "lammps==2025.7.22.2.0"

STUB_PLUGIN = """#!/bin/sh
printf '%s\\n' "$$" > "$RECORD_DIR/pid"
printf '%s\\n' "${LD_LIBRARY_PATH-}" > "$RECORD_DIR/ld_library_path"
printf '%s\\n' "$#" > "$RECORD_DIR/argc"
for arg in "$@"; do
  printf '%s\\n' "$arg" >> "$RECORD_DIR/args"
done
exit 7
"""

STUB_LAMMPS_API = r"""
#include <stdio.h>

static const char *g_infile = "(unset)";

void *lammps_open_no_mpi(int argc, char **argv, void **ptr) {
  (void)ptr;
  printf("open argc=%d argv0=%s\n", argc, argv[0]);
  return (void *)1;
}

void lammps_file(void *handle, const char *filename) {
  (void)handle;
  g_infile = filename ? filename : "(stdin)";
}

void lammps_close(void *handle) {
  (void)handle;
  printf("close infile=%s\n", g_infile);
}
"""


def _is_executable(path: Path) -> bool:
    return path.is_file() and bool(path.stat().st_mode & stat.S_IXUSR)


def _run_wrapper(args, record_dir=None, override_bin=None, extra_env=None):
    env = dict(os.environ)
    env.pop("LD_LIBRARY_PATH", None)
    if record_dir is not None:
        env["RECORD_DIR"] = str(record_dir)
    if override_bin is not None:
        env["LMP_PLUGIN_BIN"] = str(override_bin)
    else:
        env.pop("LMP_PLUGIN_BIN", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.Popen(
        [str(WRAPPER), *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


class TestLmpWithDpWrapper:
    def test_wrapper_exists_and_is_executable(self):
        assert _is_executable(WRAPPER), "bin/lmp-with-dp must be committed +x"

    def test_wrapper_execs_plugin_binary_with_deepmd_library_path(self, tmp_path):
        stub = tmp_path / "lmp-plugin-stub"
        stub.write_text(STUB_PLUGIN)
        stub.chmod(0o755)
        args = ["-in", "in.lammps", "-screen", "none", "-log", "log.lammps"]

        proc = _run_wrapper(args, record_dir=tmp_path, override_bin=stub)
        stdout, stderr = proc.communicate(timeout=30)

        assert proc.returncode == 7, (
            "wrapper must pass through the plugin binary's exit status "
            f"(exec semantics); got rc={proc.returncode}, stderr={stderr!r}"
        )
        assert (tmp_path / "ld_library_path").read_text().strip() == "/opt/deepmd/lib", (
            "wrapper must put the compose bind mount (/opt/deepmd/lib) first "
            "on LD_LIBRARY_PATH — it is the only source of libdeepmd_*.so"
        )
        assert (tmp_path / "args").read_text().splitlines() == args, (
            "wrapper must forward arguments verbatim"
        )
        assert int((tmp_path / "pid").read_text().strip()) == proc.pid, (
            "wrapper must exec (not fork) so signals/PID semantics stay LAMMPS's own"
        )

    def test_wrapper_preserves_existing_library_path(self, tmp_path):
        stub = tmp_path / "lmp-plugin-stub"
        stub.write_text(STUB_PLUGIN)
        stub.chmod(0o755)

        proc = _run_wrapper(
            ["-in", "x"], record_dir=tmp_path, override_bin=stub,
            extra_env={"LD_LIBRARY_PATH": "/opt/other"},
        )
        proc.communicate(timeout=30)

        assert (tmp_path / "ld_library_path").read_text().strip() == (
            "/opt/deepmd/lib:/opt/other"
        )

    def test_wrapper_default_exec_target_is_the_dockerfile_install_path(self):
        proc = _run_wrapper(["-in", "x"])
        _, stderr = proc.communicate(timeout=30)

        assert proc.returncode in (126, 127), (
            "without an override the wrapper must try to exec "
            f"/usr/local/bin/lmp-plugin (expected rc=126/127, got "
            f"{proc.returncode})"
        )
        assert "/usr/local/bin/lmp-plugin" in (stderr or ""), (
            "the wrapper's default exec target is where the Dockerfile "
            f"runtime stage installs the launcher; stderr={stderr!r}"
        )


class TestLmpPluginLauncher:
    @pytest.fixture(scope="class")
    def launcher_binary(self, tmp_path_factory):
        cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if cc is None:
            pytest.skip("no C compiler available to exercise the launcher")
        tmp = tmp_path_factory.mktemp("lmp-plugin-launcher")
        stub = tmp / "lammps_api_stub.c"
        stub.write_text(STUB_LAMMPS_API)
        binary = tmp / "lmp-plugin"
        subprocess.run(
            [cc, "-O2", "-o", str(binary), str(LAUNCHER), str(stub)],
            check=True,
            capture_output=True,
        )
        return binary

    def test_last_in_flag_wins(self, launcher_binary):
        args = ["-in", "first.in", "-in", "second.in", "-screen", "none"]
        out = subprocess.run(
            [str(launcher_binary), *args],
            capture_output=True, text=True, timeout=30,
        )
        assert out.returncode == 0
        assert f"open argc={1 + len(args)}" in out.stdout, (
            "the launcher must hand its full argv to lammps_open_no_mpi"
        )
        assert "close infile=second.in" in out.stdout

    def test_no_in_flag_reads_stdin(self, launcher_binary):
        out = subprocess.run(
            [str(launcher_binary)],
            capture_output=True, text=True, timeout=30,
        )
        assert out.returncode == 0
        assert "close infile=(stdin)" in out.stdout


def _dockerfile_stages(text: str) -> dict:
    """Parse a Dockerfile into a semantic stage model.

    Folds line continuations, then returns
    ``{stage_name: {"image": str, "runs": [cmd], "copies": [dict]}}``
    where each copy is
    ``{"from": stage_or_None, "sources": [str], "dest": str}``.
    """
    stages: dict = {}
    current = None
    pending = ""
    logical = []
    for raw in text.splitlines():
        line = pending + raw.strip() if pending else raw.strip()
        if line.endswith("\\"):
            pending = line[:-1].rstrip() + " "
            continue
        pending = ""
        if line and not line.startswith("#"):
            logical.append(line)
    for line in logical:
        keyword, _, rest = line.partition(" ")
        keyword = keyword.upper()
        if keyword == "FROM":
            parts = rest.split()
            if len(parts) >= 3 and parts[1].upper() == "AS":
                image, name = parts[0], parts[2]
            else:
                image = name = parts[0]
            current = name
            stages[current] = {"image": image, "runs": [], "copies": []}
        elif current is not None and keyword == "RUN":
            stages[current]["runs"].append(rest.strip())
        elif current is not None and keyword == "COPY":
            parts = rest.split()
            from_stage = None
            while parts and parts[0].startswith("--"):
                flag = parts.pop(0)
                if flag.startswith("--from="):
                    from_stage = flag.split("=", 1)[1]
            stages[current]["copies"].append(
                {"from": from_stage, "sources": parts[:-1], "dest": parts[-1]}
            )
    return stages


class TestDockerfileBuilderStage:
    def test_builder_stage_pins_the_deepmd_ci_lammps_wheel(self):
        stages = _dockerfile_stages(DOCKERFILE.read_text(encoding="utf-8"))
        assert "lmp-builder" in stages, "Dockerfile must carry the lmp-builder stage"
        builder = stages["lmp-builder"]
        pip_installs = [r for r in builder["runs"] if "pip install" in r]
        assert any(LAMMPS_WHEEL_PIN in r for r in pip_installs), (
            "the lmp-builder stage's pip install must pin the wheel "
            "deepmd-kit's CI tests against (stable_22Jul2025_update2, MPICH "
            "ABI) — any other LAMMPS generation or MPI breaks the plugin"
        )

    def test_builder_stage_compiles_the_launcher_against_the_wheel(self):
        stages = _dockerfile_stages(DOCKERFILE.read_text(encoding="utf-8"))
        builder = stages["lmp-builder"]
        assert any(
            c["sources"] == ["bin/lmp-plugin-launcher.c"] for c in builder["copies"]
        ), "the launcher source must be copied into the build stage"
        assert any(
            "gcc" in r and "launcher.c" in r and "-llammps" in r
            for r in builder["runs"]
        ), ("the wheel ships no lmp executable — the launcher must be compiled "
            "against the wheel's liblammps.so")


class TestDockerfileRuntimeWiring:
    def test_runtime_ships_launcher_library_and_mpich(self):
        stages = _dockerfile_stages(DOCKERFILE.read_text(encoding="utf-8"))
        runtime = stages["runtime"]
        from_builder = [c for c in runtime["copies"] if c["from"] == "lmp-builder"]
        assert any(c["dest"] == "/usr/local/bin/lmp-plugin" for c in from_builder), (
            "the launcher must land at the wrapper's default exec path"
        )
        assert any(c["dest"] == "/opt/lammps/" for c in from_builder), (
            "liblammps.so must ship at the launcher's rpath"
        )
        assert any(c["dest"] == "/opt/lammps.libs/" for c in from_builder), (
            "the wheel's auditwheel libs must ship next to liblammps.so"
        )
        assert any("libmpich12" in r for r in runtime["runs"]), (
            "the runtime image must install the MPICH runtime — the "
            "MPICH-built liblammps.so DT_NEEDEDs libmpi.so.12"
        )

    def test_runtime_exposes_the_dp_wrapper_at_runner_default(self):
        stages = _dockerfile_stages(DOCKERFILE.read_text(encoding="utf-8"))
        runtime = stages["runtime"]
        assert any(
            "ln -sf" in r and "/usr/local/bin/lmp-with-dp" in r for r in runtime["runs"]
        ), ("/usr/local/bin/lmp-with-dp is LAMMPSRunner's DP default — the "
            "runtime stage must expose the wrapper there")
