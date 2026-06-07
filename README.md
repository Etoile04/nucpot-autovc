# ⚛️ NucPot AutoVC

**Automated Verification System for Interatomic Potentials**

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![LAMMPS](https://img.shields.io/badge/LAMMPS-Stable-red.svg)](https://www.lammps.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-91%2B%20passing-green.svg)]()

A FastAPI service that runs [LAMMPS](https://www.lammps.org/) simulations to compute physical properties of interatomic potentials and grades them against experimental and DFT reference values. Designed for the nuclear materials community, supporting unary (U, Mo, Zr, Nb, …) and binary (U-Mo, U-Zr) systems.

---

## 📖 Overview

Interatomic potentials are the foundation of atomistic simulations. NucPot AutoVC automates the tedious process of verifying whether a potential reproduces known material properties — lattice constants, cohesive energies, elastic constants, bulk moduli, and vacancy formation energies — and assigns transparent A–F grades.

The system exposes a REST API for submitting verification jobs, manages potential metadata via [Supabase](https://supabase.com/) (PostgreSQL), and dispatches LAMMPS calculations through a Celery/Redis task queue. Results are stored persistently and exportable as JSON or PDF reports.

---

## 🏗️ Architecture

```
                    ┌──────────────────────────┐
                    │   Cloudflare Tunnel      │
                    │   verify.nucpot.dpdns.org│
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │     FastAPI REST API      │
                    │   (uvicorn, port 8002)    │
                    └──┬──────────┬─────────┬──┘
                       │          │         │
            ┌──────────▼──┐  ┌───▼─────┐  ┌▼───────────────┐
            │  PostgreSQL  │  │  Redis  │  │   Supabase     │
            │  (nucpot db) │  │ (queue) │  │   REST API     │
            └──────────────┘  └────┬────┘  └────────────────┘
                                   │
                          ┌────────▼────────┐
                          │  Celery Worker  │
                          │  (LAMMPS runner)│
                          └────────┬────────┘
                                   │
                          ┌────────▼────────┐
                          │   LAMMPS (lmp)  │
                          │   + Potential   │
                          │   + Structure   │
                          └─────────────────┘
```

**Data flow:**

1. Client submits a verification request via the REST API.
2. API creates a `VerificationJob` in PostgreSQL and enqueues a Celery task.
3. Celery worker generates crystal structures, writes LAMMPS input decks (with pair_style compatibility layer), and runs `lmp_serial`.
4. Results are parsed, graded (A–F), and stored.
5. Client polls status or fetches the final report.

---

## ✨ Features

- **5 computed properties**: lattice constant, cohesive energy, elastic constants (C₁₁, C₁₂, C₄₄), bulk modulus, vacancy formation energy
- **A–F grading engine**: A ≤ 1%, B ≤ 3%, C ≤ 5%, D ≤ 10%, F > 10% deviation from reference
- **4 verification templates**: basic, mechanical, defect, comprehensive
- **8+ potential formats**: EAM, EAM/FS, MEAM, MTP (`.mtp`), DeepMD (`.pb`/`.pth`), Stillinger-Weber, Buckingham, ZBL + Coulomb
- **Multi-element support**: unary and binary alloys with automatic structure generation
- **Reference data**: built-in experimental/DFT values (U, Mo, Zr, U-Mo, U-Zr, Nb, …) + Materials Project API + NFMD database adapters
- **Reference gap analysis**: identifies element–property pairs lacking reliable reference values
- **Supabase integration**: reads potential metadata from Supabase REST API (not local SQLite)
- **Batch verification**: submit multiple potentials in one request
- **Export**: JSON and PDF report generation
- **Docker + docker-compose**: one-command deployment
- **91+ tests**: unit + integration with pytest

---

## 🚀 Quick Start

### Prerequisites

- Python ≥ 3.10
- [LAMMPS](https://www.lammps.org/) (`lmp_serial` on PATH or configured via `LAMMPS_BIN`)
- Redis (for Celery task queue)

### Install

```bash
git clone https://github.com/Etoile04/nucpot-autovc.git
cd nucpot-autovc
pip install -e ".[dev]"
```

### Configure

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL, SUPABASE_URL, SUPABASE_SECRET_KEY, etc.
```

### Run

```bash
# Start Redis (if not already running)
redis-server &

# Start Celery worker
celery -A autovc.workers.celery_app worker --loglevel=info --concurrency=2 &

# Start API
uvicorn autovc.main:app --host 0.0.0.0 --port 8002 --reload
```

### Verify

```bash
curl http://localhost:8002/api/health
# → {"status": "ok"}
```

### Run Tests

```bash
pytest -v
```

---

## 📡 API Reference

All endpoints are prefixed with `/api`.

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |

### Potentials

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/potentials` | List all potentials (from Supabase) |
| `POST` | `/api/potentials` | Register a new potential |
| `GET` | `/api/potentials/{id}` | Get potential details |

### Verification

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/verify` | Submit a verification job |
| `GET` | `/api/verify/{id}` | Poll verification status |
| `GET` | `/api/verify/{id}/report` | Get verification report |
| `GET` | `/api/verify/{id}/report/export` | Export report (JSON/PDF) |
| `GET` | `/api/verify/templates` | List available templates |
| `POST` | `/api/verify/submit` | Submit batch verification |

### Reference Values

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/verify/references` | List reference values |
| `POST` | `/api/verify/references` | Add reference value |
| `PUT` | `/api/verify/references` | Update reference value |
| `DELETE` | `/api/verify/references` | Delete reference value |

### Example: Submit a Verification

```bash
curl -X POST http://localhost:8002/api/verify \
  -H "Content-Type: application/json" \
  -d '{
    "potential_id": "EAM_U_Mendelev",
    "template": "comprehensive",
    "elements": ["U"]
  }'
```

### Example: Get Report

```bash
curl http://localhost:8002/api/verify/<job_id>/report
```

---

## ⚙️ Configuration

Environment variables (set in `.env` or Docker environment):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./autovc.db` | PostgreSQL or SQLite connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection for Celery |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/0` | Celery result backend |
| `SUPABASE_URL` | — | Supabase project URL |
| `SUPABASE_PUBLISHABLE_KEY` | — | Supabase publishable key (sb_publishable_..., safe for client-side) |
| `SUPABASE_SECRET_KEY` | — | Supabase secret key (sb_secret_..., backend only, bypasses RLS) |
| `LAMMPS_BIN` | `lmp_serial` | Path to LAMMPS executable |

---

## 🐳 Deployment

### Docker Compose

```bash
docker-compose up -d
```

This starts three services:

- **`api`** — FastAPI on port 8002 (mapped to host 8002)
- **`worker`** — Celery worker with LAMMPS
- **`redis`** — Message broker

The API joins the external `nucpot_default` Docker network to access the nucpot PostgreSQL database.

### Production (Systemd)

On the ThinkStation, the service runs under systemd with a conda environment:

```bash
# The service file typically lives at:
# /etc/systemd/system/nucpot-autovc.service
sudo systemctl start nucpot-autovc
sudo systemctl status nucpot-autovc
```

### Cloudflare Tunnel

A [Cloudflare Named Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) exposes the API at:

```
https://verify.nucpot.dpdns.org
```

---

## 💻 Development

### Setup

```bash
pip install -e ".[dev]"
pre-commit install   # if configured
```

### Project Structure

```
nucpot-autovc/
├── src/autovc/
│   ├── __init__.py
│   ├── __main__.py              # Entry point
│   ├── main.py                  # FastAPI app factory
│   ├── config.py                # Pydantic settings
│   ├── models.py                # SQLAlchemy models
│   ├── schemas.py               # Pydantic schemas
│   ├── database.py              # DB session management
│   ├── supabase_client.py       # Supabase REST API client
│   ├── supabase_db.py           # Supabase DB integration
│   ├── structure_generator.py   # Crystal structure generation
│   ├── pair_style_compat.py     # LAMMPS pair_style compatibility
│   ├── scheduler.py             # Job scheduling
│   ├── elastic_backfill.py      # Elastic constant backfill
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py            # REST API endpoints
│   ├── core/
│   │   ├── __init__.py
│   │   ├── grading.py           # A–F grading engine
│   │   ├── templates.py         # Verification templates
│   │   ├── properties.py        # Property definitions
│   │   └── calculator.py        # Calculation orchestrator
│   ├── runners/
│   │   ├── __init__.py
│   │   └── lammps_runner.py     # LAMMPS execution engine
│   ├── reference/
│   │   ├── __init__.py
│   │   ├── data.py              # Built-in reference data
│   │   ├── property_mapping.py  # Property name normalization
│   │   ├── gap_analyzer.py      # Reference gap detection
│   │   ├── cache_query.py       # Cached reference queries
│   │   ├── mp_adapter.py        # Materials Project adapter
│   │   ├── db_migrate.py        # Reference DB migrations
│   │   ├── write_ref_value.py   # Reference value writer
│   │   ├── adapters/
│   │   │   ├── nfmd.py          # NFMD database adapter
│   │   │   ├── mp.py            # Materials Project adapter
│   │   │   ├── wiki.py          # Wiki-based adapter
│   │   │   └── ontology.py      # Ontology adapter
│   │   └── data/                # Static reference data files
│   └── workers/
│       ├── __init__.py
│       ├── celery_app.py        # Celery configuration
│       └── tasks.py             # Task definitions
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_grading.py
│   ├── test_pair_compat.py
│   ├── test_structure_gen.py
│   ├── test_properties.py
│   ├── test_templates.py
│   ├── test_workers.py
│   ├── test_integration.py
│   ├── test_e2e.py
│   ├── test_supabase_lammps.py
│   ├── test_reference_data.py
│   └── ...                     # 91+ tests total
├── scripts/                     # Utility scripts
├── docs/                        # Documentation
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── .env.example
```

### Adding a New Property

1. Define the property in `core/properties.py`.
2. Implement the LAMMPS calculation in `runners/lammps_runner.py`.
3. Add reference values in `reference/data.py` or via the API.
4. Update grading in `core/grading.py` if needed.
5. Add tests in `tests/`.

### Adding a New Potential Format

1. Add the pair_style mapping in `pair_style_compat.py`.
2. Handle file discovery and LAMMPS input generation.
3. Add tests in `tests/test_pair_compat.py`.

---

## 🎯 Grading System

| Grade | Max Deviation | Meaning |
|-------|--------------|---------|
| **A** | ≤ 1% | Excellent agreement |
| **B** | ≤ 3% | Good agreement |
| **C** | ≤ 5% | Acceptable |
| **D** | ≤ 10% | Poor |
| **F** | > 10% | Unreliable |

Each property is graded individually; the overall grade is the worst individual grade (conservative).

---

## 📋 Verification Templates

| Template | Properties |
|----------|-----------|
| `basic` | Lattice constant, cohesive energy |
| `mechanical` | + Elastic constants (C₁₁, C₁₂, C₄₄), bulk modulus |
| `defect` | + Vacancy formation energy |
| `comprehensive` | All 5 properties |

---

## 🔬 Supported Potential Formats

| Format | LAMMPS pair_style | File Extension |
|--------|-------------------|----------------|
| EAM (Dynamo/Finnis-Sinclair) | `pair_style eam/alloy` | `.eam.alloy` |
| EAM/FS | `pair_style eam/fs` | `.eam.fs` |
| MEAM | `pair_style meam` | `.meam` + library |
| MTP (Moment Tensor) | `pair_style mtp` | `.mtp` |
| DeepMD | `pair_style deepmd` | `.pb` / `.pth` |
| Stillinger-Weber | `pair_style sw` | `.sw` |
| Buckingham | `pair_style buck` | — |
| ZBL + Coulomb | `pair_style hybrid/overlay zbl coul/long` | — |

---

## 📊 Reference Data Sources

- **Experimental**: U, Mo, Zr, U-Mo, U-Zr, Nb, and more
- **DFT calculations**: First-principles data from published literature
- **Materials Project API**: Automated lookups via `mp_adapter.py`
- **NFMD Database**: Nuclear Fuel Materials Database adapter

The `gap_analyzer.py` module identifies element–property pairs where reference data is missing or uncertain, guiding future data collection efforts.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---

<p align="center">
  Built for the <strong>nuclear materials modeling</strong> community 🏗️⚛️
</p>
