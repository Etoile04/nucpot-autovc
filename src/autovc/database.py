"""Database engine and session management.

Supports both SQLite (development) and PostgreSQL/Supabase (production).
Automatically detects from DATABASE_URL.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def _normalize_db_url(url: str) -> str:
    """Normalize DATABASE_URL for SQLAlchemy."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def get_engine():
    url = _normalize_db_url(os.environ.get("DATABASE_URL", "sqlite:///./autovc.db"))
    if url.startswith("sqlite"):
        return create_engine(url, echo=False)
    else:
        # PostgreSQL/Supabase
        return create_engine(url, echo=False, pool_size=5, max_overflow=10)


def get_session_factory():
    engine = get_engine()
    return sessionmaker(bind=engine)


def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
