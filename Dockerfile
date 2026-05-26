# NucPot AutoVC - FastAPI Verification Service
# Multi-stage build: builder (kimpy compile) + runtime

FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git pkg-config wget \
    && rm -rf /var/lib/apt/lists/*

# Build kim-api from source
WORKDIR /build
RUN git clone --depth 1 https://github.com/openkim/kim-api.git && \
    cd kim-api && mkdir build && cd build && \
    cmake .. -DCMAKE_INSTALL_PREFIX=/usr/local && \
    make -j$(nproc) && make install && ldconfig

# Install kimpy (needs pkg-config to find kim-api)
ENV PKG_CONFIG_PATH=/usr/local/lib/pkgconfig
RUN pip install --no-cache-dir kimpy

# Install project deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    redis-tools \
    && rm -rf /var/lib/apt/lists/*

# Copy kim-api from builder
COPY --from=builder /usr/local/lib/libkim-api* /usr/local/lib/
COPY --from=builder /usr/local/lib/pkgconfig/ /usr/local/lib/pkgconfig/
COPY --from=builder /usr/local/include/kim-api/ /usr/local/include/kim-api/
COPY --from=builder /usr/local/lib/cmake/kim-api/ /usr/local/lib/cmake/kim-api/
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
RUN ldconfig

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .

# Download KIM models (EAM for U, Mo, Zr)
RUN kim-api-collections-management install user EAM_Dynamo_ZhouJW_2004_U__MO_149316438765_001 || true
RUN kim-api-collections-management install user EAM_Dynamo_ZhouJW_2004_U_Mo__MO_681318545861_001 || true
RUN kim-api-collections-management install user EAM_Dynamo_Mendelev_2007_Zr__MO_895293190254_001 || true

EXPOSE 8000

ENV DATABASE_URL=sqlite:///./autovc.db
ENV REDIS_URL=redis://redis:6379/0
ENV CELERY_BROKER_URL=redis://redis:6379/0
ENV CELERY_RESULT_BACKEND=redis://redis:6379/0

CMD ["uvicorn", "autovc.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--factory"]
