"""Tests for elastic_backfill module."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from autovc.elastic_backfill import ElasticBackfiller, BackfillStats
from autovc.reference.write_ref_value import WriteStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(prop_name: str, computed_value: float, unit: str = "GPa"):
    """Create a fake verification_results row."""
    return {
        "id": 1,
        "job_id": 10,
        "property_name": prop_name,
        "computed_value": computed_value,
        "unit": unit,
        "verification_jobs": {
            "status": "completed",
            "potential_id": 5,
            "structure": "BCC",
            "potentials": {
                "name": "EAM_Dynamo_Ackland_W__MO_141627175497_005",
                "species": ["W"],
            },
        },
    }


def _make_client():
    """Return a MagicMock that mimics supabase-py client."""
    return MagicMock()


def _mock_fetch_chain(client, data):
    """Wire client.table("verification_results") to return *data* on execute.

    The fetch chain is: table().select(...).like(...).eq(...).execute().
    Each intermediate call returns the same chain mock.
    """
    chain = MagicMock()
    chain.select.return_value = chain
    chain.like.return_value = chain
    chain.eq.return_value = chain
    chain.execute.return_value = SimpleNamespace(data=data)

    def _table(name):
        if name == "verification_results":
            return chain
        return MagicMock()

    client.table.side_effect = _table
    return chain


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestExtractC11C12C44(unittest.TestCase):
    """extract_elastic_constants should parse elastic_constants_X rows."""

    def test_extract_c11(self):
        row = _make_row("elastic_constants_C11", 522.45)
        result = ElasticBackfiller.extract_elastic_constants(row)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "C11")
        self.assertAlmostEqual(result["value"], 522.45)
        self.assertEqual(result["unit"], "GPa")

    def test_extract_c12(self):
        row = _make_row("elastic_constants_C12", 203.10)
        result = ElasticBackfiller.extract_elastic_constants(row)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "C12")
        self.assertAlmostEqual(result["value"], 203.10)

    def test_extract_c44(self):
        row = _make_row("elastic_constants_C44", 160.80)
        result = ElasticBackfiller.extract_elastic_constants(row)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "C44")
        self.assertAlmostEqual(result["value"], 160.80)


class TestExtractMissingData(unittest.TestCase):
    """extract_elastic_constants returns None for bad / missing data."""

    def test_wrong_property_prefix(self):
        row = _make_row("bulk_modulus", 160.0)
        self.assertIsNone(ElasticBackfiller.extract_elastic_constants(row))

    def test_unknown_elastic_component(self):
        row = _make_row("elastic_constants_C33", 280.0)
        # C33 is not in ELASTIC_PROPERTIES (C11, C12, C44 only)
        self.assertIsNone(ElasticBackfiller.extract_elastic_constants(row))

    def test_none_value(self):
        row = _make_row("elastic_constants_C11", None)
        self.assertIsNone(ElasticBackfiller.extract_elastic_constants(row))

    def test_non_numeric_value(self):
        row = _make_row("elastic_constants_C11", "not_a_number")
        self.assertIsNone(ElasticBackfiller.extract_elastic_constants(row))

    def test_empty_dict(self):
        self.assertIsNone(ElasticBackfiller.extract_elastic_constants({}))

    def test_string_value_coerced(self):
        """A string that *can* be float()-ed should still work."""
        row = _make_row("elastic_constants_C11", "500.0")
        result = ElasticBackfiller.extract_elastic_constants(row)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["value"], 500.0)


class TestDryRunNoWrite(unittest.TestCase):
    """dry_run=True must NOT call .insert() on the reference_values table."""

    def test_no_insert_in_dry_run(self):
        client = _make_client()
        fetch_data = [_make_row("elastic_constants_C11", 522.0)]
        _mock_fetch_chain(client, fetch_data)

        backfiller = ElasticBackfiller(supabase_client=client)
        stats = backfiller.run_backfill(dry_run=True)

        # In dry-run mode stats.written is incremented but no actual insert
        self.assertGreater(stats.written, 0)

        # Verify that .insert() was never called on any table
        for c in client.method_calls:
            if "insert" in str(c):
                self.fail(f"insert() was called during dry_run: {c}")


class TestDeduplication(unittest.TestCase):
    """write_to_reference_db should detect duplicates via dedup_check."""

    @patch("autovc.elastic_backfill.dedup_check", return_value=True)
    @patch("autovc.elastic_backfill.passes_quality_gate", return_value=True)
    def test_duplicate_detected(self, mock_qg, mock_dedup):
        client = _make_client()

        # existing records returned by ref query
        ref_chain = MagicMock()
        ref_chain.select.return_value = ref_chain
        ref_chain.eq.return_value = ref_chain
        ref_chain.execute.return_value = SimpleNamespace(
            data=[{"element_system": "W", "phase": "bcc", "property": "C11",
                   "method": "strain-energy", "source": "nucpot-autovc:test"}]
        )

        def _table(name):
            return ref_chain

        client.table.side_effect = _table

        backfiller = ElasticBackfiller(supabase_client=client)
        result = backfiller.write_to_reference_db(
            constants={"name": "C11", "value": 522.0, "unit": "GPa"},
            material="W",
            source="nucpot-autovc:test",
        )

        self.assertEqual(result.status, WriteStatus.DUPLICATE)
        self.assertEqual(backfiller.stats.duplicates, 1)

    @patch("autovc.elastic_backfill.dedup_check", return_value=False)
    @patch("autovc.elastic_backfill.passes_quality_gate", return_value=True)
    def test_new_record_written(self, mock_qg, mock_dedup):
        client = _make_client()

        # First call: select existing -> empty; second call: insert
        select_chain = MagicMock()
        select_chain.select.return_value = select_chain
        select_chain.eq.return_value = select_chain
        select_chain.execute.return_value = SimpleNamespace(data=[])

        insert_chain = MagicMock()
        insert_chain.insert.return_value = insert_chain
        insert_chain.execute.return_value = SimpleNamespace(data=[{"id": "new"}])

        call_count = [0]

        def _table(name):
            call_count[0] += 1
            if call_count[0] <= 4:
                # eq() is chained 4 times for the select
                return select_chain
            return insert_chain

        client.table.side_effect = _table

        backfiller = ElasticBackfiller(supabase_client=client)
        result = backfiller.write_to_reference_db(
            constants={"name": "C11", "value": 522.0, "unit": "GPa"},
            material="W",
            source="nucpot-autovc:new_potential",
        )

        self.assertEqual(result.status, WriteStatus.WRITTEN_AUTO)
        self.assertEqual(backfiller.stats.written, 1)


class TestRunBackfillDry(unittest.TestCase):
    """Full dry-run backfill pipeline."""

    def test_dry_run_pipeline(self):
        client = _make_client()
        rows = [
            _make_row("elastic_constants_C11", 522.45),
            _make_row("elastic_constants_C12", 203.10),
            _make_row("elastic_constants_C44", 160.80),
            # Non-elastic row — should be skipped
            _make_row("lattice_constant", 3.16, "Å"),
        ]
        _mock_fetch_chain(client, rows)

        backfiller = ElasticBackfiller(supabase_client=client)
        stats = backfiller.run_backfill(dry_run=True)

        # 4 rows queried (all returned by fetch), 3 extracted (elastic only)
        self.assertEqual(stats.queried, 4)
        self.assertEqual(stats.extracted, 3)
        # In dry-run: written = extracted (all pass)
        self.assertEqual(stats.written, 3)
        self.assertEqual(stats.duplicates, 0)
        self.assertEqual(stats.errors, 0)

    def test_empty_results(self):
        client = _make_client()
        _mock_fetch_chain(client, [])

        backfiller = ElasticBackfiller(supabase_client=client)
        stats = backfiller.run_backfill(dry_run=True)

        self.assertEqual(stats.queried, 0)
        self.assertEqual(stats.extracted, 0)
        self.assertEqual(stats.written, 0)


if __name__ == "__main__":
    unittest.main()
