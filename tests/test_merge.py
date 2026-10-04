#!/usr/bin/env python3
"""P2.8 -- Import merge: preview/diff + verified/estimated, no silent overwrite.

An import (JSON snapshot or FUT.GG set) must:
  * produce a PREVIEW/diff before anything is applied,
  * tag each incoming record as `verified` (trusted source) or `estimated`,
  * and NEVER silently overwrite a hand-edited value -- such a change must be
    flagged `needsConfirmation` and skipped unless the caller confirms.
"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server_harness import load_server  # noqa: E402

srv = load_server()


def _state():
    return {
        "schemaVersion": 2,
        "players": [
            {"id": "p1", "name": "Same", "score": 100, "buyPrice": 500},
            {"id": "p2", "name": "Edited", "score": 250, "buyPrice": 900},
        ],
        "galleries": [
            {"id": "g1", "name": "Ex", "slots": 15},
        ],
    }


class TestMergePreview(unittest.TestCase):
    def test_preview_does_not_mutate_inputs(self):
        cur, inc = _state(), {"players": [{"id": "p2", "score": 1}]}
        cur_snapshot = copy.deepcopy(cur)
        srv.merge_state(cur, inc, source="fut.gg")
        self.assertEqual(cur, cur_snapshot, "merge_state must be pure")

    def test_added_vs_changed_vs_unchanged(self):
        cur = _state()
        inc = {"players": [
            {"id": "p1", "name": "Same", "score": 100, "buyPrice": 500},  # unchanged
            {"id": "p2", "name": "Edited", "score": 260, "buyPrice": 900},  # changed
            {"id": "p3", "name": "New", "score": 50},                       # added
        ]}
        prev = srv.merge_state(cur, inc, source="fut.gg")
        by_id = {e["id"]: e for e in prev["players"]}
        self.assertEqual(by_id["p1"]["status"], "unchanged")
        self.assertEqual(by_id["p2"]["status"], "changed")
        self.assertEqual(by_id["p3"]["status"], "added")

    def test_summary_counts(self):
        cur = _state()
        inc = {"players": [
            {"id": "p2", "score": 260},
            {"id": "p3", "score": 50},
        ]}
        s = srv.merge_state(cur, inc, source="fut.gg")["summary"]
        self.assertEqual(s["playersAdded"], 1)
        self.assertEqual(s["playersChanged"], 1)
        self.assertEqual(s["playersUnchanged"], 0)

    def test_diff_lists_the_changed_field(self):
        cur = _state()
        inc = {"players": [{"id": "p2", "score": 260}]}
        e = next(x for x in srv.merge_state(cur, inc, source="fut.gg")["players"]
                 if x["id"] == "p2")
        ch = {c["field"]: (c["old"], c["new"]) for c in e["changes"]}
        self.assertEqual(ch["score"], (250, 260))


class TestProvenanceTagging(unittest.TestCase):
    def test_trusted_source_is_verified(self):
        prev = srv.merge_state({}, {"players": [{"id": "p1"}]}, source="fut.gg")
        self.assertEqual(prev["players"][0]["provenance"], "verified")

    def test_unknown_source_is_estimated(self):
        prev = srv.merge_state({}, {"players": [{"id": "p1"}]}, source="json")
        self.assertEqual(prev["players"][0]["provenance"], "estimated")

    def test_slots_estimated_forces_estimated(self):
        inc = {"galleries": [{"id": "g1", "slotsEstimated": True}]}
        prev = srv.merge_state({}, inc, source="fut.gg")
        self.assertEqual(prev["galleries"][0]["provenance"], "estimated")

    def test_summary_counts_estimated(self):
        inc = {"players": [{"id": "p1"}], "galleries": [{"id": "g1", "estimated": True}]}
        s = srv.merge_state({}, inc, source="json")["summary"]
        self.assertEqual(s["estimated"], 2)


class TestManualGuard(unittest.TestCase):
    def test_overwriting_a_manual_price_needs_confirmation(self):
        cur = _state()
        inc = {"players": [{"id": "p2", "buyPrice": 1000}]}  # user had 900
        e = next(x for x in srv.merge_state(cur, inc, source="fut.gg")["players"]
                 if x["id"] == "p2")
        self.assertTrue(e["needsConfirmation"])

    def test_non_manual_field_change_does_not_need_confirmation(self):
        cur = _state()
        inc = {"players": [{"id": "p2", "name": "Renamed"}]}
        e = next(x for x in srv.merge_state(cur, inc, source="fut.gg")["players"]
                 if x["id"] == "p2")
        self.assertFalse(e["needsConfirmation"])

    def test_adding_a_new_price_does_not_need_confirmation(self):
        cur = {"players": [{"id": "p2", "name": "x"}], "galleries": []}
        inc = {"players": [{"id": "p2", "buyPrice": 1000}]}   # old had none
        e = next(x for x in srv.merge_state(cur, inc, source="fut.gg")["players"])
        self.assertFalse(e["needsConfirmation"])


class TestApplyMerge(unittest.TestCase):
    def test_unconfirmed_manual_overwrite_is_skipped(self):
        cur = _state()
        inc = {"players": [{"id": "p2", "buyPrice": 1000}]}
        prev = srv.merge_state(cur, inc, source="fut.gg")
        new, applied = srv.apply_merge(cur, inc, prev)   # confirm=False
        kept = next(p for p in new["players"] if p["id"] == "p2")
        self.assertEqual(kept["buyPrice"], 900, "manual value must survive")
        self.assertEqual(applied["skipped"], 1)
        self.assertIn("p2", applied["skippedIds"])

    def test_confirmed_overwrite_is_applied(self):
        cur = _state()
        inc = {"players": [{"id": "p2", "buyPrice": 1000}]}
        prev = srv.merge_state(cur, inc, source="fut.gg")
        new, applied = srv.apply_merge(cur, inc, prev, confirm=True)
        kept = next(p for p in new["players"] if p["id"] == "p2")
        self.assertEqual(kept["buyPrice"], 1000)
        self.assertEqual(applied["applied"], 1)

    def test_new_records_are_added(self):
        cur = _state()
        inc = {"players": [{"id": "p9", "name": "Fresh", "score": 10}]}
        prev = srv.merge_state(cur, inc, source="fut.gg")
        new, applied = srv.apply_merge(cur, inc, prev)
        self.assertTrue(any(p["id"] == "p9" for p in new["players"]))
        self.assertEqual(applied["applied"], 1)

    def test_apply_does_not_mutate_current(self):
        cur = _state()
        cur_snapshot = copy.deepcopy(cur)
        inc = {"players": [{"id": "p9", "name": "Fresh"}]}
        prev = srv.merge_state(cur, inc, source="fut.gg")
        srv.apply_merge(cur, inc, prev)
        self.assertEqual(cur, cur_snapshot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
