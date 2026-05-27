"""Application configuration via environment variables."""

import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """AutoVC configuration. All values can be overridden via env vars."""

    # Database - supports both SQLite and Supabase/PostgreSQL
    DATABASE_URL: str = "sqlite:///./autovc.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Supabase (for NucPot integration)
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # LAMMPS binary
    LAMMPS_BIN: str = os.environ.get("LAMMPS_BIN", "lmp_serial")

    # Grading thresholds (relative error) — updated per spec
    GRADING_THRESHOLD_A: float = 0.02   # ≤2%  → A
    GRADING_THRESHOLD_B: float = 0.05   # ≤5%  → B
    GRADING_THRESHOLD_C: float = 0.10   # ≤10% → C
    GRADING_THRESHOLD_D: float = 0.20   # ≤20% → D
    # >20% → F

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def get_settings() -> Settings:
    return Settings()
