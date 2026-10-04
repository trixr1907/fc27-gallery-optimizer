#!/usr/bin/env python3
"""P2.10 -- price SCENARIOS (best/base/worst), provenance and staleness.

Separate from test_prices.py (which pins the snapshot shape). Here we test that a
scenario actually RESOLVES to a different number, that staleness is detected, and
that the metadata (source/updatedAt) is preserved.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server_harness import load_server  # noqa: E402

srv = load_server()


class TestScenarioValue(unittest.TestCase):
    def test_bare_number_is_scenario_agnostic(self):
        for sc in ("best", "base", "worst"):
            self.assertEqual(srv.scenario_value(1200, sc), 1200)

    def test_snapshot_scenarios(self):
        snap = {"value": 1000, "best": 900, "worst": 1200}
        self.assertEqual(srv.scenario_value(snap, "best"), 900)
        self.assertEqual(srv.scenario_value(snap, "base"), 1000)
        self.assertEqual(srv.scenario_value(snap, "worst"), 1200)

    def test_missing_scenario_falls_back_to_base(self):
        snap = {"value": 1000, "best": 900}   # no 'worst'
        self.assertEqual(srv.scenario_value(snap, "worst"), 1000)

    def test_unknown_scenario_degrades_to_base(self):
        snap = {"value": 1000, "best": 900, "worst": 1200}
        self.assertEqual(srv.scenario_value(snap, "banana"), 1000)

    def test_v2_snapshot_is_scenario_complete(self):
        s = srv.price_snapshot(1000)
        self.assertEqual(s["best"], 1000)
        self.assertEqual(s["worst"], 1000)
        self.assertEqual(s["value"], 1000)


class TestProvenance(unittest.TestCase):
    def test_price_updated_at_prefers_p2_field(self):
        self.assertEqual(srv.price_updated_at({"priceUpdatedAt": "T", "fetchedAt": "O"}), "T")

    def test_price_updated_at_falls_back_to_fetchedat(self):
        self.assertEqual(srv.price_updated_at({"fetchedAt": "O"}), "O")

    def test_bare_number_has_no_stamp(self):
        self.assertIsNone(srv.price_updated_at(1200))

    def test_price_source(self):
        self.assertEqual(srv.price_source({"source": "fut.gg"}), "fut.gg")
        self.assertIsNone(srv.price_source(1200))


class TestStaleness(unittest.TestCase):
    def test_fresh_is_not_stale(self):
        import datetime
        now = datetime.datetime(2026, 10, 5, tzinfo=datetime.timezone.utc)
        snap = {"value": 1, "priceUpdatedAt": "2026-10-04T00:00:00Z"}
        self.assertFalse(srv.price_stale(snap, max_age_seconds=30 * 24 * 3600, now=now))

    def test_old_is_stale(self):
        import datetime
        now = datetime.datetime(2026, 10, 5, tzinfo=datetime.timezone.utc)
        snap = {"value": 1, "priceUpdatedAt": "2026-01-01T00:00:00Z"}
        self.assertTrue(srv.price_stale(snap, max_age_seconds=30 * 24 * 3600, now=now))

    def test_exactly_at_the_boundary_is_not_stale(self):
        import datetime
        now = datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)
        snap = {"value": 1, "priceUpdatedAt": "2026-01-02T00:00:00Z"}  # 30 days
        self.assertFalse(srv.price_stale(snap, max_age_seconds=30 * 24 * 3600, now=now))

    def test_bare_number_is_never_stale(self):
        self.assertFalse(srv.price_stale(1200))

    def test_garbage_timestamp_is_not_stale(self):
        self.assertFalse(srv.price_stale({"value": 1, "priceUpdatedAt": "not-a-date"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
