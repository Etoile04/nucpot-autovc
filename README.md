# NucPot AutoVC

Automated Verification System for Interatomic Potentials. Phase 1 (L1: Passive Pipeline).

## Quick Start
pip install -e .[dev]
pytest -v

## API Endpoints
- GET /api/health
- POST /api/potentials - Register potential
- GET /api/potentials - List all
- GET /api/potentials/{id} - Get one
- POST /api/verification - Submit verification job
- GET /api/verification/{id} - Get status

## Architecture
FastAPI -> Celery/Redis -> Worker(kimpy/kimvv/ASE) -> SQLite

## Supported Properties
- lattice_constant (A)
- cohesive_energy (eV/atom)
- elastic_constants (GPa)

## Grading
A<=1%, B<=3%, C<=5%, D<=10%, F>10%

## Reference Data
U, Mo, Zr, U-Mo, U-Zr (experimental/DFT)
