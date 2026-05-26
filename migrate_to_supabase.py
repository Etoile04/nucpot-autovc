"""Supabase migration script for nucpot-autovc.

Usage:
    DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres python migrate_to_supabase.py

This creates the autovc tables (potentials, verification_jobs, verification_results)
in the target Supabase/PostgreSQL database.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("Usage: DATABASE_URL=postgresql://... python migrate_to_supabase.py")
        sys.exit(1)

    print(f"Migrating to: {url.split('@')[-1]}")  # Don't print credentials

    from supabase_db import init_supabase_db
    engine = init_supabase_db()

    # Verify tables exist
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name IN "
            "('potentials', 'verification_jobs', 'verification_results')"
        ))
        tables = [r[0] for r in result]
    print(f"Created tables: {tables}")

    expected = {"potentials", "verification_jobs", "verification_results"}
    if expected.issubset(set(tables)):
        print("✅ Migration successful!")
    else:
        print(f"❌ Missing tables: {expected - set(tables)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
