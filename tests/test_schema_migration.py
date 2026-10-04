#!/usr/bin/env python3
"""P2.5 -- State schema version + forward migration.

A saved state must keep working after the schema grows. migrate_state() is
conservative (adds fields, normalises aliases, wraps bare prices as snapshots)
and idempotent. A state NEWER than this build is rejected (no silent downgrade).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server_harness import load_server  # noqa: E402

srv = load_server()


def legacy_state():
    """A v1-shaped state: no schemaVersion, bare numeric prices, variant names."""
    return {
        "settings": {"coins": 270000, "taxRate": 0.05, "objective": "eff", "maxBundle": 15},
        "players": [
            {"id": "p1", "itemId": "p1", "name": "A", "score": 200,
             "buyPrice": 1000, "resalePrice": 950, "special": "Hero"},
            {"id": "p2", "itemId": "p2", "name": "B", "score": 150,
             "buyPrice": 500, "resalePrice": 480},
        ],
        "galleries": [
            {"id": "totw", "name": "TOTW", "slots": 20,
             "eligibility": {"type": "rarity", "value": "TOTW"},
             "thresholds": {"D": 10, "C": 125000, "B": 175000, "A": 300000, "S": 550000},
             "rewards": {"D": 5, "C": 15, "B": 30, "A": 50, "S": 75},
             "sourceUrl": "https://www.fut.gg/fut-gallery/rarities/totw/"},
        ],
    }


class TestMigrateVersioning(unittest.TestCase):
    def test_missing_version_treated_as_v1(self):
        st, start = srv.migrate_state(legacy_state())
        self.assertEqual(start, 1)
        self.assertEqual(st["schemaVersion"], srv.SCHEMA_VERSION)

    def test_already_current_is_noop(self):
        st, start = srv.migrate_state(legacy_state())
        st2, start2 = srv.migrate_state(st)
        self.assertEqual(start2, srv.SCHEMA_VERSION)
        self.assertEqual(st2, st, "second migration must not change anything")

    def test_newer_schema_rejected(self):
        bad = legacy_state()
        bad["schemaVersion"] = srv.SCHEMA_VERSION + 1
        with self.assertRaises(ValueError):
            srv.migrate_state(bad)

    def test_too_old_schema_rejected(self):
        bad = legacy_state()
        bad["schemaVersion"] = 0
        with self.assertRaises(ValueError):
            srv.migrate_state(bad)

    def test_non_dict_rejected(self):
        with self.assertRaises(ValueError):
            srv.migrate_state([])

    def test_bad_version_string_defaults_to_v1(self):
        bad = legacy_state()
        bad["schemaVersion"] = "not-a-number"
        st, start = srv.migrate_state(bad)
        self.assertEqual(start, 1)
        self.assertEqual(st["schemaVersion"], srv.SCHEMA_VERSION)


class TestMigrateContent(unittest.TestCase):
    def test_bare_prices_become_snapshots(self):
        st, _ = srv.migrate_state(legacy_state())
        for p in st["players"]:
            self.assertIsInstance(p["buyPrice"], dict)
            self.assertEqual(p["buyPrice"]["value"], 1000 if p["id"] == "p1" else 500)
            self.assertTrue(p["buyPrice"]["fetchedAt"].endswith("Z"))

    def test_special_alias_canonicalised(self):
        st, _ = srv.migrate_state(legacy_state())
        self.assertEqual(st["players"][0]["special"], "heroic")

    def test_gallery_gains_fetched_at_when_sourced(self):
        st, _ = srv.migrate_state(legacy_state())
        g = st["galleries"][0]
        self.assertIn("fetchedAt", g)
        self.assertTrue(g["fetchedAt"].endswith("Z"))

    def test_game_numbers_untouched(self):
        before = legacy_state()
        st, _ = srv.migrate_state(before)
        g = st["galleries"][0]
        self.assertEqual(g["slots"], 20)
        self.assertEqual(g["thresholds"], before["galleries"][0]["thresholds"])
        self.assertEqual(g["rewards"], before["galleries"][0]["rewards"])
        self.assertEqual(st["settings"], before["settings"])

    def test_ids_eligibility_stringified(self):
        st0 = legacy_state()
        st0["galleries"].append({
            "id": "custom", "name": "Custom", "slots": 3,
            "eligibility": {"type": "ids", "ids": [1, 2, 3]},
            "thresholds": {}, "rewards": {}})
        st, _ = srv.migrate_state(st0)
        ids = st["galleries"][1]["eligibility"]["ids"]
        self.assertEqual(ids, ["1", "2", "3"])

    def test_players_without_prices_unaffected(self):
        st0 = legacy_state()
        st0["players"].append({"id": "p3", "itemId": "p3", "name": "C", "score": 90})
        st, _ = srv.migrate_state(st0)
        p3 = [p for p in st["players"] if p["id"] == "p3"][0]
        self.assertNotIn("buyPrice", p3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
