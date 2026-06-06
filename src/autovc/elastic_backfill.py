"""Elastic constant backfiller: extract C11/C12/C44 from completed verifications
and write them as reference values.

Designed to be called from a CLI or orchestrator. All Supabase/DB interactions
are injected so the module is fully testable with unittest.mock.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from autovc.reference.write_ref_value import (
    WriteResult,
    WriteStatus,
    dedup_check,
    passes_quality_gate,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ELASTIC_PROPERTIES = ("C11", "C12", "C44")
UNIT = "GPa"
METHOD = "strain-energy"
CONFIDENCE = "high"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BackfillStats:
    """Running counters for a backfill pass."""

    queried: int = 0
    extracted: int = 0
    written: int = 0
    duplicates: int = 0
    rejected: int = 0
    errors: int = 0

    def summary(self) -> str:
        return (
            f"queried={self.queried} extracted={self.extracted} "
            f"written={self.written} duplicates={self.duplicates} "
            f"rejected={self.rejected} errors={self.errors}"
        )


# ---------------------------------------------------------------------------
# ElasticBackfiller
# ---------------------------------------------------------------------------


class ElasticBackfiller:
    """Backfill elastic constant reference values from verification results.

    Parameters
    ----------
    supabase_client : module-like object
        Must expose ``get_verification``-style async helpers or a synchronous
        ``table().select().eq().execute()`` pattern.  For the initial
        implementation we accept a *supabase* client instance that follows
        the ``supabase-py`` API:
            client.table("verification_results").select(...).eq(...).execute()
    ref_client : module-like object or None
        Client for the ``reference_values`` table.  Falls back to
        *supabase_client* when omitted.
    """

    def __init__(self, supabase_client, ref_client=None):
        self.client = supabase_client
        self.ref_client = ref_client or supabase_client
        self.stats = BackfillStats()

    # ------------------------------------------------------------------
    # 1. Fetch completed verifications with elastic constant results
    # ------------------------------------------------------------------

    def fetch_completed_verifications(self) -> list[dict]:
        """Query Supabase for completed verification results containing
        elastic constants (property_name starting with ``elastic_constants_``).

        Returns a list of rows from ``verification_results`` joined with
        enough metadata to identify the material (element_system / species).
        """
        try:
            resp = (
                self.client.table("verification_results")
                .select(
                    "id, job_id, property_name, computed_value, unit, "
                    "verification_jobs!inner(status, potential_id, structure, "
                    "potentials!inner(name, species))"
                )
                .like("property_name", "elastic_constants_%")
                .eq("verification_jobs.status", "completed")
                .execute()
            )
            rows = resp.data or []
            self.stats.queried = len(rows)
            return rows
        except Exception as exc:
            logger.error("fetch_completed_verifications failed: %s", exc)
            self.stats.errors += 1
            return []

    # ------------------------------------------------------------------
    # 2. Extract elastic constants from a verification result dict
    # ------------------------------------------------------------------

    @staticmethod
    def extract_elastic_constants(result: dict) -> Optional[dict]:
        """Extract C11, C12, C44 from a verification result row.

        Parameters
        ----------
        result : dict
            A single row from ``verification_results``.  Expected keys:
            ``property_name`` (e.g. ``"elastic_constants_C11"``),
            ``computed_value``, ``unit``.

        Returns
        -------
        dict with keys ``name`` (C11/C12/C44), ``value``, ``unit`` or
        ``None`` if the data cannot be parsed.
        """
        prop_name = result.get("property_name", "")
        if not prop_name.startswith("elastic_constants_"):
            return None

        short = prop_name.replace("elastic_constants_", "")
        if short not in ELASTIC_PROPERTIES:
            return None

        value = result.get("computed_value")
        if value is None:
            return None

        # Guard against non-numeric values
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None

        return {
            "name": short,
            "value": value,
            "unit": result.get("unit", UNIT),
        }

    # ------------------------------------------------------------------
    # 3. Write a single extracted constant to the reference_values table
    # ------------------------------------------------------------------

    def write_to_reference_db(
        self,
        constants: dict,
        material: str,
        source: str,
        phase: str = "bcc",
    ) -> WriteResult:
        """Build a reference-value record and attempt to write it.

        Uses the quality-gate and dedup logic from ``write_ref_value``.

        Parameters
        ----------
        constants : dict
            Output of :meth:`extract_elastic_constants` — must contain
            ``name``, ``value``, ``unit``.
        material : str
            Element symbol or composition string (e.g. ``"W"``, ``"Fe"``, ``"CuAu"``).
        source : str
            Provenance string, e.g. ``"nucpot-autovc:potential_name"``.
        phase : str
            Crystal structure (default ``"bcc"``).

        Returns
        -------
        WriteResult from the quality/dedup pipeline.
        """
        prop = constants["name"]
        ref_record = {
            "element_system": material,
            "phase": phase,
            "property": prop,
            "value": constants["value"],
            "unit": constants.get("unit", UNIT),
            "method": METHOD,
            "source": source,
            "confidence": CONFIDENCE,
        }

        # Dedup: query existing records with same key
        try:
            existing_resp = (
                self.ref_client.table("reference_values")
                .select("element_system, phase, property, method, source")
                .eq("element_system", material)
                .eq("property", prop)
                .eq("method", METHOD)
                .eq("source", source)
                .execute()
            )
            existing = existing_resp.data or []
        except Exception:
            existing = []

        # Quality gate
        if not passes_quality_gate(ref_record):
            self.stats.rejected += 1
            return WriteResult(WriteStatus.REJECTED, reason="quality gate failed")

        # Dedup check
        if dedup_check(ref_record, existing):
            self.stats.duplicates += 1
            return WriteResult(WriteStatus.DUPLICATE, reason="duplicate record")

        # Write
        try:
            self.ref_client.table("reference_values").insert(ref_record).execute()
            self.stats.written += 1
            return WriteResult(WriteStatus.WRITTEN_AUTO, reason="auto-written")
        except Exception as exc:
            logger.error("write_to_reference_db failed: %s", exc)
            self.stats.errors += 1
            return WriteResult(WriteStatus.REJECTED, reason=str(exc))

    # ------------------------------------------------------------------
    # 4. Main backfill loop
    # ------------------------------------------------------------------

    def run_backfill(self, dry_run: bool = True) -> BackfillStats:
        """Run the full backfill pipeline.

        Parameters
        ----------
        dry_run : bool
            When *True*, extract and validate but **skip** the actual
            database write.  Useful for auditing what *would* happen.

        Returns
        -------
        BackfillStats with counts.
        """
        self.stats = BackfillStats()
        rows = self.fetch_completed_verifications()

        for row in rows:
            extracted = self.extract_elastic_constants(row)
            if extracted is None:
                continue

            self.stats.extracted += 1

            # Resolve material and source from the joined row
            job_info = row.get("verification_jobs") or {}
            pot_info = job_info.get("potentials") or {}
            material = ""
            species = pot_info.get("species")
            if isinstance(species, list):
                material = "".join(species)
            elif isinstance(species, str):
                material = species
            phase = (job_info.get("structure") or "bcc").lower()
            source = f"nucpot-autovc:{pot_info.get('name', 'unknown')}"

            if dry_run:
                logger.info(
                    "[DRY-RUN] would write %s %s=%.2f %s source=%s",
                    material,
                    extracted["name"],
                    extracted["value"],
                    extracted["unit"],
                    source,
                )
                self.stats.written += 1
                continue

            self.write_to_reference_db(
                constants=extracted,
                material=material,
                source=source,
                phase=phase,
            )

        logger.info("Backfill complete: %s", self.stats.summary())
        return self.stats
