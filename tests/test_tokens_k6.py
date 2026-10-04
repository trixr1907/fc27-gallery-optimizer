#!/usr/bin/env python3
"""K2 -- cumulative token semantics.

`tokens(g, grade)` is the SUM of every grade reward up to and including the
reached grade (NOT incremental). Verified against the frozen FUT.GG numbers
(R5: parse fixtures for the inputs, engine assertions only on constructed data).

K6 rides along here: `itemId` is card identity, `playerKey` is the canonical
player (for "Multiples!"). Two items may share a `playerKey`; they must never
share an `itemId`.
"""
import os
import sys
import unittest

# Allow both `python -m unittest discover -s tests` and `-m unittest tests.test_x`.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from engine_harness import EngineTestCase  # noqa: E402

# Frozen reward tables (from the parser fixtures / plan §1.7).
TOTW = {"thresholds": {"D": 10, "C": 125000, "B": 175000, "A": 300000, "S": 550000},
        "rewards": {"D": 5, "C": 15, "B": 30, "A": 50, "S": 75}}          # sum 175
MALAGA = {"thresholds": {"D": 10, "C": 300, "B": 400, "A": 700, "S": 900},
          "rewards": {"D": 0, "C": 0, "B": 5, "A": 8, "S": 15}}            # sum 28
PL = {"thresholds": {"D": 10, "C": 400000, "B": 800000, "A": 1900000, "S": 4000000},
      "rewards": {"D": 10, "C": 35, "B": 50, "A": 70, "S": 100}}           # sum 265


class TestTokensCumulative(EngineTestCase):
    """tokens() must accumulate, not return the single grade reward."""

    def test_totw_full(self):
        self.assertEqual(self.engine.call("tokens", TOTW, "S"), 175)

    def test_malaga_full(self):
        self.assertEqual(self.engine.call("tokens", MALAGA, "S"), 28)

    def test_pl_full(self):
        self.assertEqual(self.engine.call("tokens", PL, "S"), 265)

    def test_pl_grade_c_is_45_of_265(self):
        """Description: 'earns 45 of 265' -> D+C = 10+35 = 45 (cumulative)."""
        self.assertEqual(self.engine.call("tokens", PL, "C"), 45)

    def test_cumulative_monotonic(self):
        """Each higher grade must be >= the previous (never incremental-only)."""
        seq = [self.engine.call("tokens", TOTW, g) for g in "DCBAS"]
        self.assertEqual(seq, [5, 20, 50, 100, 175])
        self.assertEqual(seq, sorted(seq))

    def test_totw_grade_b(self):
        self.assertEqual(self.engine.call("tokens", TOTW, "B"), 50)  # 5+15+30

    def test_null_grade_is_zero(self):
        self.assertEqual(self.engine.call("tokens", TOTW, None), 0)

    def test_semantics_label_is_cumulative(self):
        """Guard against a future rename to 'incremental' in the source."""
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "engine", "engine.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("Cumulative Gallery Tokens", src)
        self.assertNotIn("Incremental Gallery Tokens", src)


class TestMultiplesDataModel(EngineTestCase):
    """K6 identity model.

    itemId    = identity of one CARD (two card versions of a player differ).
    playerKey = canonical PLAYER (only "Multiples!" uses it).

    Required guarantees:
      * same playerKey, DIFFERENT itemIds -> both may enter the lineup;
      * same itemId -> at most ONE may enter the lineup.
    """

    def _score(self, items):
        return self.engine.call("score", items, {"countTopTags": 10})

    def test_two_items_same_playerkey_trigger_multiples(self):
        """Two cards of the SAME player (different itemId) -> Multiples! pays."""
        items = [
            {"itemId": "card-1", "playerKey": "player-x", "name": "X", "score": 100},
            {"itemId": "card-2", "playerKey": "player-x", "name": "X", "score": 100},
        ]
        r = self._score(items)
        # multi: 2 items -> tier 2..2 -> 10% of 200 = 20
        self.assertIn(20, r["tags"], "Multiples! (2 same playerKey) must pay 20")

    def test_same_playerkey_different_itemids_both_allowed(self):
        """Both card versions of one player may sit in the lineup (Multiples!)."""
        items = [
            {"itemId": "c1", "playerKey": "same", "name": "S", "score": 400},
            {"itemId": "c2", "playerKey": "same", "name": "S", "score": 300},
            {"itemId": "c3", "playerKey": "other", "name": "O", "score": 100},
        ]
        r = self.engine.call("lineup", items, 2)
        ids = [x["itemId"] for x in r["items"]]
        keys = [x["playerKey"] for x in r["items"]]
        self.assertEqual(len(ids), len(set(ids)), "itemIds must be distinct")
        self.assertEqual(keys.count("same"), 2,
                         "two card versions of one player must both be selectable")

    def test_same_itemid_at_most_one_in_lineup(self):
        """Same itemId (same card) -> at most one instance in the lineup."""
        items = [
            {"itemId": "dup", "playerKey": "a", "name": "A", "score": 500},
            {"itemId": "dup", "playerKey": "a", "name": "A", "score": 500},
            {"itemId": "b", "playerKey": "b", "name": "B", "score": 100},
        ]
        r = self.engine.call("lineup", items, 2)
        ids = [x["itemId"] for x in r["items"]]
        self.assertEqual(len(ids), len(set(ids)), "no two lineup items may share an itemId")
        self.assertEqual(ids.count("dup"), 1)

    def test_itemid_dedup_keeps_highest_score(self):
        """When the same itemId appears twice, the higher-scored copy is kept."""
        items = [
            {"itemId": "dup", "playerKey": "a", "name": "A", "score": 100},
            {"itemId": "dup", "playerKey": "a", "name": "A", "score": 900},
        ]
        r = self.engine.call("lineup", items, 5)
        self.assertEqual(len(r["items"]), 1)
        self.assertEqual(r["items"][0]["score"], 900)


class TestEligibilityIds(EngineTestCase):
    """Engine-level coverage for the `ids` eligibility path (K4/H2).

    The gallery is passed as the SECOND argument and `eligible()` reads
    `g.eligibility` -- so the type/ids fields must be NESTED under
    `eligibility`. A bare `{"type":"ids", ...}` is NOT a gallery and falls
    through to the `sets` branch (this is the mistake that made the first
    probe return false for every case).
    """

    def _g(self, **eligibility):
        return {"id": "g-ids", "eligibility": eligibility}

    def test_member_item_is_eligible(self):
        g = self._g(type="ids", ids=["c1", "c2"])
        self.assertTrue(self.engine.call("eligible", {"itemId": "c1"}, g))
        self.assertTrue(self.engine.call("eligible", {"itemId": "c2"}, g))

    def test_non_member_item_is_not_eligible(self):
        g = self._g(type="ids", ids=["c1", "c2"])
        self.assertFalse(self.engine.call("eligible", {"itemId": "c9"}, g))

    def test_falls_back_to_record_id_when_itemid_absent(self):
        """`p.itemId || p.id`: a legacy record without itemId still matches."""
        g = self._g(type="ids", ids=["p-7"])
        self.assertTrue(self.engine.call("eligible", {"id": "p-7"}, g))

    def test_ids_path_requires_type_key(self):
        """Without `type: 'ids'` the ids list is ignored (sets branch)."""
        g = self._g(ids=["c1"])
        self.assertFalse(self.engine.call("eligible", {"itemId": "c1"}, g))

    def test_gender_guard_precedes_ids(self):
        """A gender mismatch rejects even a listed itemId."""
        g = self._g(type="ids", ids=["c1"], gender="women")
        self.assertFalse(self.engine.call("eligible", {"itemId": "c1", "gender": "men"}, g))
        self.assertTrue(self.engine.call("eligible", {"itemId": "c1", "gender": "women"}, g))


if __name__ == "__main__":
    unittest.main(verbosity=2)
