#!/bin/sh
# NFM-5281 — reproducible build of bin/lmp-plugin (linux/aarch64).
#
# WHY: Debian trixie's `lammps` package (20250204+dfsg.1-2) is built
# WITHOUT the PLUGIN package, so `plugin load` fails with "Unknown
# command" — verified in-container 2026-10-08 on
# nucpot-autovc-repo-api-1. The deepmd pair style arrives as a runtime
# plugin (libdeepmd_lmpplugin.so, staged under deepmd-plugin/, provenance
# in MANIFEST.md), so AutoVC needs an LAMMPS of the same generation built
# WITH:
#   PKG_PLUGIN            — the `plugin load` command itself
#   PKG_KSPACE            — the plugin resolves LAMMPS_NS::KSpace
#                           typeinfo from the host binary (MANIFEST.md,
#                           dlopen note 2026-10-03)
#   PKG_MANYBODY, PKG_MOLECULE — keep the binary a drop-in for the
#                           classical templates if one ever routes here
# FFT=KISS avoids the fftw3 dev dependency (the DP path never uses PPPM).
#
# Tag patch_4Feb2025 == Debian's 20250204 version, so the vendored binary
# matches the distro LAMMPS the classical paths still use. Source comes from
# the Debian archive (lammps_20250204+dfsg.1.orig) via the same USTC mirror
# the Dockerfile uses — byte-identical upstream tree AND domestic-mirror
# fast (codeload.github.com crawls at ~40 KB/s from this network).
#
# Usage (from repo root, on the Apple Silicon deploy host — containers are
# linux/aarch64 and the host is arm64, so no emulation):
#   ./bin/build-lmp-plugin.sh
# Produces bin/lmp-plugin. ~15 min on the Mac Studio.
set -eu

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$REPO_ROOT/bin/lmp-plugin"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/lmp-plugin-build.XXXXXXXX")
trap 'rm -rf "$WORK"' EXIT

echo "==> building in debian:trixie (matches the runtime image's glibc)"
docker run --rm \
  -v "$WORK":/out \
  debian:trixie sh -eu -c '
    # GFW workaround: same USTC mirror the Dockerfile uses, + deb-src for
    # apt-get source (trixie ships Types: deb only)
    sed -i -e "s|deb.debian.org|mirrors.ustc.edu.cn|g" \
           -e "s/^Types: deb$/Types: deb deb-src/" /etc/apt/sources.list.d/debian.sources
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends build-essential cmake
    mkdir /build
    cd /build
    # orig tarball == upstream patch_4Feb2025 (dfsg: docs/fonts stripped —
    # irrelevant to the build) + debian patches NOT applied (we build plain
    # upstream cmake; the distro binary keeps serving the classical paths)
    apt-get source --download-only lammps
    tar -xf lammps_*.orig.tar.* --strip-components=1
    cmake -S /build/cmake -B /build/build \
      -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_OMP=on \
      -DBUILD_MPI=off \
      -DLAMMPS_EXCEPTIONS=on \
      -DFFT=KISS \
      -DPKG_PLUGIN=on \
      -DPKG_KSPACE=on \
      -DPKG_MANYBODY=on \
      -DPKG_MOLECULE=on
    cmake --build /build/build -j"$(nproc)"
    cp /build/build/lmp /out/lmp-plugin
    /out/lmp-plugin -h | head -2
  '

install -m 0755 "$WORK/lmp-plugin" "$OUT"
echo "==> wrote $OUT (linux/aarch64 — verify inside a container, not on macOS)"
file "$OUT"
