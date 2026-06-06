"""
Slow-line verification scheduler for nucpot-autovc.

Provides a configuration-driven cron framework that periodically discovers
unverified potentials and submits low-priority verification tasks.
"""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_SCHEDULE: dict[str, Any] = {
    "enabled": False,
    "schedule_type": "interval",
    "interval_hours": 24,
    "cron_expression": "0 2 * * *",
    "max_concurrent": 1,
    "priority_filter": ["P2", "P3"],
    "potential_types": ["eam", "eam/fs", "mtp"],
    "dry_run": True,
    "batch_size": 10,
    "log_level": "INFO",
}

_CONFIG_FILENAME = "scheduler_config.json"


def _resolve_config_path() -> Path:
    """Return the path to the bundled default config file."""
    return Path(__file__).resolve().parent / _CONFIG_FILENAME


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class VerificationScheduler:
    """Configuration-driven slow-line verification scheduler.

    Reads a JSON config file (or falls back to built-in defaults) and
    orchestrates periodic discovery → filter → submit cycles.

    Parameters
    ----------
    config_path:
        Path to a JSON configuration file.  When *None* the bundled
        ``scheduler_config.json`` is loaded.  Missing keys are always
        back-filled from :data:`DEFAULT_SCHEDULE`.
    overrides:
        Optional dict of config values that win over the file (useful for
        tests or CLI flags).
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> None:
        self._config = deepcopy(DEFAULT_SCHEDULE)
        self._load_config(config_path)
        if overrides:
            self._config.update(overrides)
        self._log_config()

    # ---- config helpers ---------------------------------------------------

    @property
    def config(self) -> dict[str, Any]:
        return deepcopy(self._config)

    def _load_config(self, config_path: str | Path | None) -> None:
        path = Path(config_path) if config_path else _resolve_config_path()
        if path.is_file():
            try:
                with open(path) as fh:
                    file_cfg = json.load(fh)
                self._config.update(file_cfg)
                logger.info("Scheduler config loaded from %s", path)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load config %s: %s – using defaults", path, exc)
        else:
            logger.info("Config file %s not found – using built-in defaults", path)

    def _log_config(self) -> None:
        logger.setLevel(self._config.get("log_level", "INFO"))
        logger.debug("Effective scheduler config: %s", self._config)

    # ---- query helpers (mock-friendly) ------------------------------------

    async def get_pending_verifications(self) -> list[dict[str, Any]]:
        """Return potentials that have not yet been verified.

        In production this would query Supabase via
        :pymod:`autovc.supabase_client`.  The method is designed to be
        easily monkey-patched / mocked in tests.
        """
        from autovc.supabase_client import get_potential, create_verification

        # Placeholder: in a real implementation we would query the
        # ``potentials`` table for entries with no matching
        # ``verification_jobs`` row.  For now return an empty list so
        # the scheduler framework is functional.
        logger.info("Querying Supabase for pending verifications…")
        return []

    # ---- filtering --------------------------------------------------------

    @staticmethod
    def filter_by_priority(
        potentials: list[dict[str, Any]],
        allowed: list[str],
    ) -> list[dict[str, Any]]:
        """Keep only potentials whose *priority* field is in *allowed*."""
        allowed_set = set(allowed)
        return [p for p in potentials if p.get("priority") in allowed_set]

    @staticmethod
    def filter_by_potential_type(
        potentials: list[dict[str, Any]],
        allowed: list[str],
    ) -> list[dict[str, Any]]:
        """Keep only potentials whose *type* (or *potential_type*) is in *allowed*."""
        allowed_set = set(allowed)
        return [
            p
            for p in potentials
            if p.get("type") in allowed_set or p.get("potential_type") in allowed_set
        ]

    # ---- submission -------------------------------------------------------

    async def submit_batch(
        self,
        potentials: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Submit verification jobs for *potentials*, respecting *max_concurrent*.

        Returns a list of submitted verification records (empty in dry-run).
        """
        cfg = self._config
        max_conc = cfg["max_concurrent"]
        candidates = potentials[:max_conc]
        results: list[dict[str, Any]] = []

        if cfg["dry_run"]:
            for p in candidates:
                logger.info("[DRY-RUN] Would submit verification for %s", p.get("id", p.get("name")))
            return results

        for p in candidates:
            try:
                from autovc.supabase_client import create_verification

                record = {
                    "potential_id": p.get("id"),
                    "status": "pending",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "priority": p.get("priority", "P3"),
                }
                result = await create_verification(record)
                results.append(result)
                logger.info("Submitted verification for %s", p.get("id"))
            except Exception as exc:
                logger.error("Failed to submit verification for %s: %s", p.get("id"), exc)

        return results

    # ---- main cycle -------------------------------------------------------

    async def run_cycle(self) -> dict[str, Any]:
        """Execute one full scheduler cycle: discover → filter → submit.

        Returns a summary dict useful for logging / monitoring.
        """
        cfg = self._config
        summary: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dry_run": cfg["dry_run"],
            "enabled": cfg["enabled"],
            "discovered": 0,
            "after_priority_filter": 0,
            "after_type_filter": 0,
            "submitted": 0,
            "skipped_disabled": False,
        }

        if not cfg["enabled"]:
            logger.info("Scheduler is disabled – skipping cycle")
            summary["skipped_disabled"] = True
            return summary

        # 1. discover
        pending = await self.get_pending_verifications()
        summary["discovered"] = len(pending)

        # 2. filter by priority
        filtered = self.filter_by_priority(pending, cfg["priority_filter"])
        summary["after_priority_filter"] = len(filtered)

        # 3. filter by potential type
        filtered = self.filter_by_potential_type(filtered, cfg["potential_types"])
        summary["after_type_filter"] = len(filtered)

        # 4. submit
        submitted = await self.submit_batch(filtered)
        summary["submitted"] = len(submitted)

        logger.info("Scheduler cycle complete: %s", summary)
        return summary
