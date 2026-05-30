"""DB schema migration for reference_values table enhancement.

Ensures the reference_values table has all columns needed by the ref-gap-fill system.
Provides column validation and ALTER TABLE SQL generation for missing columns.

Migrated from material-llm-wiki/scripts/db_migrate.py into nucpot-autovc.
"""

from dataclasses import dataclass


EXPECTED_COLUMNS = [
    "id", "element_system", "phase", "property", "value",
    "unit", "method", "source", "source_doi",
    "confidence", "needs_review", "cache_level",
    "uncertainty", "temperature", "created_at", "updated_at",
]

NEW_COLUMNS = {
    "confidence": "TEXT DEFAULT 'high' CHECK (confidence IN ('high', 'medium', 'low'))",
    "needs_review": "BOOLEAN DEFAULT FALSE",
    "cache_level": "TEXT CHECK (cache_level IN ('L1', 'L2', 'L3A', 'L3B'))",
    "uncertainty": "FLOAT",
    "temperature": "FLOAT DEFAULT 0",
    "created_at": "TIMESTAMP DEFAULT NOW()",
    "updated_at": "TIMESTAMP DEFAULT NOW()",
}


@dataclass
class MigrationResult:
    missing_columns: list[str]
    sql: str


def validate_schema(existing_columns: list[str]) -> MigrationResult:
    """Compare existing columns against EXPECTED_COLUMNS, return missing + SQL."""
    missing = [col for col in EXPECTED_COLUMNS if col not in existing_columns]
    sql = generate_migration_sql(missing)
    return MigrationResult(missing_columns=missing, sql=sql)


def generate_migration_sql(missing: list[str] = None) -> str:
    """Generate ALTER TABLE statements for missing columns."""
    if missing is None:
        missing = list(NEW_COLUMNS.keys())

    statements = []
    for col in missing:
        if col in NEW_COLUMNS:
            statements.append(
                f"ALTER TABLE reference_values ADD COLUMN IF NOT EXISTS {col} {NEW_COLUMNS[col]};"
            )

    # Index for common query patterns
    statements.append(
        "CREATE INDEX IF NOT EXISTS idx_ref_values_lookup ON reference_values(element_system, phase, property);"
    )
    statements.append(
        "CREATE INDEX IF NOT EXISTS idx_ref_values_needs_review ON reference_values(needs_review) WHERE needs_review = TRUE;"
    )

    return "\n".join(statements)
