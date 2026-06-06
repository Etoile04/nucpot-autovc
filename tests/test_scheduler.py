"""Tests for the slow-line verification scheduler."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from autovc.scheduler import DEFAULT_SCHEDULE, VerificationScheduler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def scheduler() -> VerificationScheduler:
    """A scheduler with default config and dry-run enabled."""
    return VerificationScheduler(overrides={"dry_run": True, "enabled": True})


@pytest.fixture
def sample_potentials() -> list[dict]:
    """A heterogeneous mix of potentials for filter testing."""
    return [
        {"id": "p1", "name": "Cu_eam", "type": "eam", "priority": "P1"},
        {"id": "p2", "name": "Al_eam_fs", "type": "eam/fs", "priority": "P2"},
        {"id": "p3", "name": "Fe_mtp", "type": "mtp", "priority": "P3"},
        {"id": "p4", "name": "Ni_eam", "type": "eam", "priority": "P2"},
        {"id": "p5", "name": "Ti_meam", "type": "meam", "priority": "P3"},
        {"id": "p6", "name": "W_eam", "potential_type": "eam", "priority": "P2"},
    ]


# ---------------------------------------------------------------------------
# test_default_config_loads
# ---------------------------------------------------------------------------

class TestDefaultConfig:
    def test_default_config_loads(self, scheduler: VerificationScheduler):
        """Default configuration loads without any external file."""
        cfg = scheduler.config
        assert cfg["enabled"] is True          # overridden in fixture
        assert cfg["dry_run"] is True          # overridden in fixture
        # Values that were NOT overridden should still match DEFAULT_SCHEDULE
        assert cfg["max_concurrent"] == DEFAULT_SCHEDULE["max_concurrent"]
        assert cfg["interval_hours"] == DEFAULT_SCHEDULE["interval_hours"]
        assert cfg["priority_filter"] == DEFAULT_SCHEDULE["priority_filter"]
        assert cfg["potential_types"] == DEFAULT_SCHEDULE["potential_types"]


# ---------------------------------------------------------------------------
# test_custom_config_merge
# ---------------------------------------------------------------------------

class TestCustomConfigMerge:
    def test_custom_config_merge(self, tmp_path: Path):
        """Custom JSON file values override defaults; others stay."""
        custom = {
            "interval_hours": 6,
            "max_concurrent": 3,
            "dry_run": False,
        }
        cfg_file = tmp_path / "custom.json"
        cfg_file.write_text(json.dumps(custom))

        sched = VerificationScheduler(
            config_path=str(cfg_file),
            overrides={"enabled": True},
        )
        cfg = sched.config
        # Custom values
        assert cfg["interval_hours"] == 6
        assert cfg["max_concurrent"] == 3
        assert cfg["dry_run"] is False
        # Defaults preserved for keys not in custom file
        assert cfg["priority_filter"] == DEFAULT_SCHEDULE["priority_filter"]
        assert cfg["potential_types"] == DEFAULT_SCHEDULE["potential_types"]
        # Override applied
        assert cfg["enabled"] is True


# ---------------------------------------------------------------------------
# test_filter_by_priority
# ---------------------------------------------------------------------------

class TestFilterByPriority:
    def test_filter_by_priority(self, scheduler: VerificationScheduler, sample_potentials):
        """Only potentials with priority in the allowed list pass through."""
        allowed = ["P2", "P3"]
        result = scheduler.filter_by_priority(sample_potentials, allowed)
        ids = [p["id"] for p in result]
        assert "p1" not in ids  # P1 filtered out
        assert "p2" in ids
        assert "p3" in ids
        assert "p4" in ids
        assert "p5" in ids
        assert "p6" in ids
        assert len(result) == 5


# ---------------------------------------------------------------------------
# test_filter_by_potential_type
# ---------------------------------------------------------------------------

class TestFilterByPotentialType:
    def test_filter_by_potential_type(self, scheduler: VerificationScheduler, sample_potentials):
        """Only potentials whose type is in the allowed list pass through."""
        allowed = ["eam", "eam/fs", "mtp"]
        result = scheduler.filter_by_potential_type(sample_potentials, allowed)
        ids = [p["id"] for p in result]
        assert "p5" not in ids  # meam filtered out
        assert "p1" in ids
        assert "p2" in ids
        assert "p3" in ids
        assert "p4" in ids
        assert "p6" in ids  # uses potential_type key
        assert len(result) == 5


# ---------------------------------------------------------------------------
# test_max_concurrent_limit
# ---------------------------------------------------------------------------

class TestMaxConcurrentLimit:
    def test_max_concurrent_limit(self, sample_potentials):
        """submit_batch respects max_concurrent and only submits that many."""
        sched = VerificationScheduler(overrides={
            "enabled": True,
            "dry_run": False,
            "max_concurrent": 2,
        })
        mock_create = AsyncMock(return_value={"id": "v1", "status": "pending"})
        # create_verification is imported locally inside submit_batch from
        # autovc.supabase_client, so patch it at the source module.
        with patch("autovc.supabase_client.create_verification", mock_create):
            results = asyncio.get_event_loop().run_until_complete(
                sched.submit_batch(sample_potentials)
            )
        assert len(results) == 2


# ---------------------------------------------------------------------------
# test_dry_run_no_submission
# ---------------------------------------------------------------------------

class TestDryRunNoSubmission:
    def test_dry_run_no_submission(self, sample_potentials):
        """When dry_run=True, submit_batch returns an empty list."""
        sched = VerificationScheduler(overrides={
            "enabled": True,
            "dry_run": True,
            "max_concurrent": 5,
        })
        results = asyncio.get_event_loop().run_until_complete(
            sched.submit_batch(sample_potentials)
        )
        assert results == []


# ---------------------------------------------------------------------------
# test_run_cycle_dry
# ---------------------------------------------------------------------------

class TestRunCycleDry:
    def test_run_cycle_dry(self, sample_potentials):
        """A full dry-run cycle with mocked Supabase query produces correct summary."""
        sched = VerificationScheduler(overrides={
            "enabled": True,
            "dry_run": True,
            "max_concurrent": 1,
            "priority_filter": ["P2", "P3"],
            "potential_types": ["eam", "eam/fs", "mtp"],
        })

        # Mock get_pending_verifications to return our sample data
        sched.get_pending_verifications = AsyncMock(return_value=sample_potentials)  # type: ignore[method-assign]

        summary = asyncio.get_event_loop().run_until_complete(sched.run_cycle())

        assert summary["dry_run"] is True
        assert summary["enabled"] is True
        assert summary["skipped_disabled"] is False
        assert summary["discovered"] == 6
        # After P2/P3 Filter: p1 (P1) removed → 5
        assert summary["after_priority_filter"] == 5
        # After type filter: p5 (meam) removed → 4
        assert summary["after_type_filter"] == 4
        # dry_run: nothing actually submitted
        assert summary["submitted"] == 0

    def test_run_cycle_disabled(self):
        """When disabled, run_cycle returns immediately with skipped flag."""
        sched = VerificationScheduler(overrides={
            "enabled": False,
            "dry_run": True,
        })
        summary = asyncio.get_event_loop().run_until_complete(sched.run_cycle())
        assert summary["skipped_disabled"] is True
        assert summary["submitted"] == 0
