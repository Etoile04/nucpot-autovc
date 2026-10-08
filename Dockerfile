# NucPot AutoVC - FastAPI Verification Service
# Multi-stage build: builder (kimpy compile) + runtime

FROM python:3.12-slim AS builder

# GFW workaround: debian CDN unstable from this network; use TUNA mirror
RUN sed -i "s|deb.debian.org|mirrors.ustc.edu.cn|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true
RUN apt-get update && apt-get install -y --no-install-recommends     build-essential cmake gfortran git pkg-config wget     && rm -rf /var/lib/apt/lists/*

# Build kim-api from source (vendored copy — GFW blocks in-container git clone)
WORKDIR /build
COPY vendor/kim-api ./kim-api
RUN cd kim-api && mkdir build && cd build &&     cmake .. -DCMAKE_INSTALL_PREFIX=/usr/local &&     make -j$(nproc) && make install && ldconfig

# Install kimpy (needs pkg-config to find kim-api)
ENV PKG_CONFIG_PATH=/usr/local/lib/pkgconfig
# GFW workaround: pypi.org direct is unreliable from the docker VM; use the
# aliyun pypi mirror (TUNA rate-limits this network — "access denied" on
# /simple/kimpy/, 2026-10-08).
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && pip config set global.retries 8 && pip config set global.timeout 60
RUN pip install --no-cache-dir kimpy

# Install project deps
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# ── NFM-5281: PLUGIN-capable LAMMPS (linux/aarch64) ─────────────────────
# Debian trixie's `lammps` package (20250204) is built WITHOUT the PLUGIN
# package — `plugin load` fails with "Unknown command" (verified
# in-container 2026-10-08) — and a self-built 4Feb2025 can't host the
# deepmd plugin either: the plugin .so (deepmd-kit pip wheel) targets
# LAMMPS stable_22Jul2025_update2 with the MPICH ABI. Any other pairing
# fails two ways, both verified in-container 2026-10-08:
#   * vtable drift — on a 4Feb2025 host, pair_coeff dispatched into
#     settings() ("Failed to open file: *" / "...: 1");
#   * MPI ABI — under OpenMPI, MPI handles are pointers, so every
#     MPI-typed interface symbol mangles differently ("undefined symbol:
#     _ZN9LAMMPS_NS6Grid3d12forward_commEiPviiiS1_S1_i").
# deepmd-kit's own pyproject pins this exact wheel (DP_LAMMPS_VERSION =
# "stable_22Jul2025_update2", test dep lammps[mpi]~=2025.7.22.2.0), so we
# ship that library and stay on the CI-tested pairing. The wheel carries
# liblammps.so (MPICH-linked, PKG_PLUGIN-enabled, full symbol export) but
# no lmp executable — bin/lmp-plugin-launcher.c is the argv-compatible
# front end. Wheel libs land at /opt/lammps (+ /opt/lammps.libs per the
# auditwheel $ORIGIN/../lammps.libs rpath); the runtime stage adds the
# MPICH runtime (libmpi.so.12) the library NEEDs.
FROM python:3.12-slim AS lmp-builder
# GFW workaround: apt from the USTC mirror like the other stages (deb.debian.org
# crawls from this network), pip from aliyun (TUNA rate-limits, 2026-10-08).
RUN sed -i "s|deb.debian.org|mirrors.ustc.edu.cn|g" /etc/apt/sources.list.d/debian.sources
RUN pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple/ \
      lammps==2025.7.22.2.0
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev libmpich-dev \
    && rm -rf /var/lib/apt/lists/*
COPY bin/lmp-plugin-launcher.c /tmp/launcher.c
RUN SITE=$(python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])") \
    && gcc -O2 -o /usr/local/bin/lmp-plugin /tmp/launcher.c \
         -L"$SITE/lammps" -llammps -Wl,-rpath,/opt/lammps \
    && mkdir -p /opt/lammps /opt/lammps.libs \
    && cp -P "$SITE"/lammps/liblammps.so* /opt/lammps/ \
    && cp -rP "$SITE"/lammps.libs/. /opt/lammps.libs/

FROM python:3.12-slim AS runtime

# GFW workaround (runtime stage too — pip config from builder doesn't persist)
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_RETRIES=8 \
    PIP_TIMEOUT=60

# GFW workaround: TUNA mirror for apt
RUN sed -i "s|deb.debian.org|mirrors.ustc.edu.cn|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true
RUN apt-get update && apt-get install -y --no-install-recommends     redis-tools     && rm -rf /var/lib/apt/lists/*

# Copy kim-api from builder
COPY --from=builder /usr/local/lib/libkim-api* /usr/local/lib/
COPY --from=builder /usr/local/lib/pkgconfig/ /usr/local/lib/pkgconfig/
COPY --from=builder /usr/local/include/kim-api/ /usr/local/include/kim-api/
COPY --from=builder /usr/local/share/cmake/kim-api/ /usr/local/lib/cmake/kim-api/
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
RUN ldconfig

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .

# Download KIM models (EAM for U, Mo, Zr)
RUN kim-api-collections-management install user EAM_Dynamo_ZhouJW_2004_U__MO_149316438765_001 || true
RUN kim-api-collections-management install user EAM_Dynamo_ZhouJW_2004_U_Mo__MO_681318545861_001 || true
RUN kim-api-collections-management install user EAM_Dynamo_Mendelev_2007_Zr__MO_895293190254_001 || true

# LAMMPS: use Debian's arm64-native lammps (MANYBODY et al. included) instead
# of the vendored x86-64 bin/lmp-full which lacks MANYBODY (eam/fs) and needs
# qemu emulation + amd64 multilib. apt lammps 2025.02 covers all pair styles
# the verification templates use.
RUN apt-get update && apt-get install -y --no-install-recommends         lammps lammps-data libmpich12     && rm -rf /var/lib/apt/lists/*

# Create lmp_serial symlink at build time
RUN ln -sf /usr/bin/lmp /usr/local/bin/lmp_serial

# NFM-5281: PLUGIN-capable LAMMPS from the builder stage + the DP wrapper.
# bin/lmp-with-dp (already COPYed with the tree to /app/bin/) puts the
# staged runtime — bind-mounted at /opt/deepmd/lib by docker-compose.yml —
# on LD_LIBRARY_PATH, then execs lmp-plugin. LAMMPSRunner's DP default is
# /usr/local/bin/lmp-with-dp.
COPY --from=lmp-builder /usr/local/bin/lmp-plugin /usr/local/bin/lmp-plugin
COPY --from=lmp-builder /opt/lammps/ /opt/lammps/
COPY --from=lmp-builder /opt/lammps.libs/ /opt/lammps.libs/
RUN ln -sf /app/bin/lmp-with-dp /usr/local/bin/lmp-with-dp

# Ensure uploads dir exists
RUN mkdir -p /app/uploads

EXPOSE 8000

ENV DATABASE_URL=sqlite:///./autovc.db
# `autovc-redis` = the docker-compose service name — unique on the shared prod
# network, where a bare `redis` host collides with nucpot-prod's DNS alias (NFM-5272)
ENV REDIS_URL=redis://autovc-redis:6379/0
ENV CELERY_BROKER_URL=redis://autovc-redis:6379/0
ENV CELERY_RESULT_BACKEND=redis://autovc-redis:6379/0

ENTRYPOINT ["/bin/sh", "-c"]
CMD ["python", "-m", "uvicorn", "autovc.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--factory"]
