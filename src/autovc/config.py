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
    SUPABASE_PUBLISHABLE_KEY: str = ""  # sb_publishable_... (safe for client-side)
    SUPABASE_SECRET_KEY: str = ""       # sb_secret_... (backend only, bypasses RLS)

    # LAMMPS binary
    LAMMPS_BIN: str = os.environ.get("LAMMPS_BIN", "lmp_serial")

    # Grading thresholds (relative error) — updated per spec
    GRADING_THRESHOLD_A: float = 0.02   # ≤2%  → A
    GRADING_THRESHOLD_B: float = 0.05   # ≤5%  → B
    GRADING_THRESHOLD_C: float = 0.10   # ≤10% → C
    GRADING_THRESHOLD_D: float = 0.20   # ≤20% → D
    # >20% → F

    # Auth (Sprint 2)
    # Comma-separated SHA-256 hashes of valid API keys (avc_... prefix).
    # Generate: python -c "import hashlib; print(hashlib.sha256(b'avc_YOUR_KEY').hexdigest())"
    # Empty = dev mode (no auth enforced).
    AUTH_API_KEYS_HASHED: str = ""
    # Comma-separated SHA-256 hashes of admin-only keys.
    # If empty, all authenticated users are admin (single-user mode).
    AUTH_ADMIN_KEYS_HASHED: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def get_settings() -> Settings:
    return Settings()
