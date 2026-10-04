#!/usr/bin/env python3
"""P2.4 -- Prices are DATED SNAPSHOTS, never timeless constants.

A price stored by the app must always carry the moment it was read (`fetchedAt`)
and its source, so a later reader can tell how stale it is. These tests pin the
snapshot semantics of price_snapshot() / price_value() and the migration that
upgrades legacy bare numbers.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server_harness import load_server  # noqa: E402

srv = load_server()


class TestPriceSnapshot(unittest.TestCase):
    def test_raw_number_becomes_dated_snapshot(self):
        s = srv.price_snapshot(1200, fetched_at="2026-10-05T00:00:00Z", source="fut.gg")
        self.assertEqual(s["value"], 1200)
        self.assertEqual(s["fetchedAt"], "2026-10-05T00:00:00Z")
        self.assertEqual(s["source"], "fut.gg")

    def test_numeric_string_accepted(self):
        s = srv.price_snapshot("1350.5", fetched_at="T")
        self.assertEqual(s["value"], 1350.5)

    def test_missing_price_is_none_not_zero(self):
        for raw in (None, "", "null"):
            self.assertIsNone(srv.price_snapshot(raw), raw)

    def test_nonnumeric_is_none(self):
        self.assertIsNone(srv.price_snapshot("n/a"))
        self.assertIsNone(srv.price_snapshot("abc"))

    def test_existing_snapshot_is_preserved(self):
        prev = {"value": 900, "fetchedAt": "2026-09-01T00:00:00Z", "source": "old"}
        s = srv.price_snapshot(prev)
        self.assertEqual(s["value"], 900)
        self.assertEqual(s["fetchedAt"], "2026-09-01T00:00:00Z",
                         "an existing snapshot's timestamp must not be overwritten")
        self.assertEqual(s["source"], "old")

    def test_existing_snapshot_missing_meta_gets_filled(self):
        s = srv.price_snapshot({"value": 500}, fetched_at="NOW", source="x")
        self.assertEqual(s["fetchedAt"], "NOW")
        self.assertEqual(s["source"], "x")

    def test_price_value_reads_both_shapes(self):
        self.assertEqual(srv.price_value({"value": 700}), 700)
        self.assertEqual(srv.price_value(700), 700)
        self.assertIsNone(srv.price_value(None))

    def test_now_stamp_is_iso_z(self):
        s = srv.price_snapshot(1)
        self.assertTrue(s["fetchedAt"].endswith("Z"))
        self.assertIn("T", s["fetchedAt"])


class TestPriceFieldsDeclared(unittest.TestCase):
    def test_price_fields(self):
        self.assertEqual(set(srv.PRICE_FIELDS), {"buyPrice", "resalePrice"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
