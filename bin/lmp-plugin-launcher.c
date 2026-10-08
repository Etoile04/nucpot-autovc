/*
 * NFM-5281 — lmp-plugin: argv-compatible front end for the pip `lammps`
 * wheel's liblammps.so (LAMMPS stable_22Jul2025_update2, MPICH ABI).
 *
 * The deepmd plugin .so (deepmd-kit pip wheel) is built against exactly
 * that LAMMPS generation and against MPICH, where MPI handles are ints —
 * a different LAMMPS release shifts the Pair vtable (a 4Feb2025 host
 * dispatched pair_coeff into settings(): "Failed to open file: *"), and
 * an OpenMPI host mangles every MPI-typed interface symbol differently
 * ("undefined symbol: _ZN9LAMMPS_NS6Grid3d12forward_commEiPviiiS1_S1_i").
 * deepmd-kit's own pyproject pins this exact wheel
 * (DP_LAMMPS_VERSION = "stable_22Jul2025_update2", test dep
 * lammps[mpi]~=2025.7.22.2.0) — so we ship the same library and stay on
 * the CI-tested pairing.
 *
 * The wheel ships no `lmp` executable (it drives LAMMPS through the
 * Python module), so this launcher speaks the stable C API (library.h)
 * with lmp(1) command-line semantics: the last -in wins, no -in reads
 * stdin. lammps_open_no_mpi needs no MPI headers — LAMMPS initializes
 * MPI itself inside the library.
 */
#include <stdio.h>
#include <string.h>

extern void *lammps_open_no_mpi(int argc, char **argv, void **ptr);
extern void lammps_file(void *handle, const char *filename);
extern void lammps_close(void *handle);

int main(int argc, char **argv) {
  void *handle = NULL;
  const char *infile = NULL;
  int i;

  for (i = 1; i < argc - 1; ++i) {
    if (strcmp(argv[i], "-in") == 0) {
      infile = argv[i + 1];
    }
  }

  handle = lammps_open_no_mpi(argc, argv, &handle);
  if (handle == NULL) {
    fprintf(stderr, "lmp-plugin: lammps_open failed\n");
    return 1;
  }
  lammps_file(handle, infile); /* NULL → stdin, same as lmp */
  lammps_close(handle);
  return 0;
}
