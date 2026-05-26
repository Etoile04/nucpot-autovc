"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """AutoVC configuration. All values can be overridden via env vars."""

    # Database - supports both SQLite and Supabase/PostgreSQL
    DATABASE_URL: str = "sqlite:///./autovc.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Supabase (optional, for NucPot integration)
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # Grading thresholds (relative error)
    GRADING_THRESHOLD_A: float = 0.01   # ≤1%  → A
    GRADING_THRESHOLD_B: float = 0.03   # ≤3%  → B
    GRADING_THRESHOLD_C: float = 0.05   # ≤5%  → C
    GRADING_THRESHOLD_D: float = 0.10   # ≤10% → D
    # >10% → F

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def get_settings() -> Settings:
    return Settings()
