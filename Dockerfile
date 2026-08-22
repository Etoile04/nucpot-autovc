# NucPot AutoVC - FastAPI Verification Service
# Multi-stage build: builder (kimpy compile) + runtime

FROM python:3.12-slim AS builder

# GFW workaround: debian CDN unstable from this network; use TUNA mirror
RUN sed -i "s|deb.debian.org|mirrors.ustc.edu.cn|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true
RUN apt-get update && apt-get install -y --no-install-recommends     build-essential cmake gfortran git pkg-config wget     && rm -rf /var/lib/apt/lists/*

# Build kim-api from source
WORKDIR /build
RUN git clone --depth 1 https://github.com/openkim/kim-api.git &&     cd kim-api && mkdir build && cd build &&     cmake .. -DCMAKE_INSTALL_PREFIX=/usr/local &&     make -j$(nproc) && make install && ldconfig

# Install kimpy (needs pkg-config to find kim-api)
ENV PKG_CONFIG_PATH=/usr/local/lib/pkgconfig
RUN pip install --no-cache-dir kimpy

# Install project deps
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

FROM python:3.12-slim AS runtime

# GFW workaround: TUNA mirror for apt
RUN sed -i "s|deb.debian.org|mirrors.ustc.edu.cn|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true
RUN apt-get update && apt-get install -y --no-install-recommends     redis-tools     && rm -rf /var/lib/apt/lists/*

# Copy kim-api from builder
COPY --from=builder /usr/local/lib/libkim-api* /usr/local/lib/
COPY --from=builder /usr/local/lib/pkgconfig/ /usr/local/lib/pkgconfig/
COPY --from=builder /usr/local/include/kim-api/ /usr/local/include/kim-api/
COPY --from=builder /usr/local/share/cmake/kim-api/ /usr/local/lib/cmake/kim-api/
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
RUN ldconfig

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .

# Download KIM models (EAM for U, Mo, Zr)
RUN kim-api-collections-management install user EAM_Dynamo_ZhouJW_2004_U__MO_149316438765_001 || true
RUN kim-api-collections-management install user EAM_Dynamo_ZhouJW_2004_U_Mo__MO_681318545861_001 || true
RUN kim-api-collections-management install user EAM_Dynamo_Mendelev_2007_Zr__MO_895293190254_001 || true

# Create lmp_serial symlink at build time
RUN if [ -f /app/bin/lmp-full ]; then         ln -sf /app/bin/lmp-full /usr/local/bin/lmp_serial;     fi

# Ensure uploads dir exists
RUN mkdir -p /app/uploads

EXPOSE 8000

ENV DATABASE_URL=sqlite:///./autovc.db
ENV REDIS_URL=redis://redis:6379/0
ENV CELERY_BROKER_URL=redis://redis:6379/0
ENV CELERY_RESULT_BACKEND=redis://redis:6379/0

ENTRYPOINT ["/bin/sh", "-c"]
CMD ["python", "-m", "uvicorn", "autovc.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--factory"]
