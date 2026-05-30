"""Test DB schema migration for reference_values table."""
import pytest
from pathlib import Path

from autovc.reference.db_migrate import (
    generate_migration_sql,
    validate_schema,
    MigrationResult,
)


def test_generate_migration_sql_returns_string():
    result = generate_migration_sql()
    assert isinstance(result, str)
    assert "ALTER TABLE" in result or "CREATE TABLE" in result


def test_migration_adds_confidence_column():
    sql = generate_migration_sql()
    assert "confidence" in sql.lower()


def test_migration_adds_needs_review_column():
    sql = generate_migration_sql()
    assert "needs_review" in sql.lower()


def test_migration_adds_cache_level_column():
    sql = generate_migration_sql()
    assert "cache_level" in sql.lower()


def test_migration_adds_uncertainty_column():
    sql = generate_migration_sql()
    assert "uncertainty" in sql.lower()


def test_migration_adds_temperature_column():
    sql = generate_migration_sql()
    assert "temperature" in sql.lower()


def test_validate_schema_with_mock():
    """Validate schema against expected columns."""
    existing_columns = [
        "id", "element_system", "phase", "property", "value",
        "unit", "method", "source", "source_doi",
    ]
    result = validate_schema(existing_columns)
    assert isinstance(result, MigrationResult)
    assert len(result.missing_columns) > 0  # should find missing columns


def test_validate_schema_complete():
    """No missing columns when all expected are present."""
    existing_columns = [
        "id", "element_system", "phase", "property", "value",
        "unit", "method", "source", "source_doi",
        "confidence", "needs_review", "cache_level",
        "uncertainty", "temperature", "created_at", "updated_at",
    ]
    result = validate_schema(existing_columns)
    assert len(result.missing_columns) == 0


def test_migration_result_dataclass():
    mr = MigrationResult(
        missing_columns=["confidence"],
        sql="ALTER TABLE reference_values ADD COLUMN confidence TEXT DEFAULT 'high';",
    )
    assert mr.missing_columns == ["confidence"]
    assert "confidence" in mr.sql
