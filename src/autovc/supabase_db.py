"""Supabase/PostgreSQL database layer for nucpot-autovc.

Replaces the SQLite default with Supabase (PostgreSQL) backend.
Uses the same ORM models - only engine configuration differs.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from autovc.database import Base


def get_supabase_engine():
    """Create engine connected to Supabase PostgreSQL."""
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    )
    # Convert postgres:// to postgresql:// if needed
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(url, echo=False, pool_size=5, max_overflow=10)


def get_supabase_session_factory():
    """Session factory bound to Supabase."""
    engine = get_supabase_engine()
    return sessionmaker(bind=engine)


def init_supabase_db():
    """Create all tables in Supabase."""
    engine = get_supabase_engine()
    # Import models to register them
    import autovc.models  # noqa: F401
    Base.metadata.create_all(engine)
    return engine
