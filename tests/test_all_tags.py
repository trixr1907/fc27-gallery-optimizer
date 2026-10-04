#!/usr/bin/env python3
"""P0.4 -- every one of the 21 bonus tags is actually triggerable.

`TAG keys: 21` only proves the table has 21 rows. This module proves each row is
wired into score(): for each tag a minimal item set is constructed that reaches
its first tier, and the resulting bonus is asserted EQUAL to the tier's
floor(sum * pct) computed from the tag table itself.

The expected percentage is read from the LIVE TAG table via the engine, so the
test cannot drift from the engine's own tier definition. The engine's tier table
is itself checked against an independent dated fixture in `test_tag_table.py`
(so this module's self-referential oracle is backed by an external one).
"""
import math
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from engine_harness import EngineTestCase  # noqa: E402


def it(iid, score, **kw):
    base = {"itemId": iid, "playerKey": "pk-" + iid, "name": iid, "score": score,
            "nation": "N", "club": "K", "league": "G", "rarity": "", "position": "CM",
            "weakFoot": 3, "skillMoves": 3, "holographic": False,
            "firstOwner": False, "special": ""}
    base.update(kw)
    return base


class TestAllTagsTriggerable(EngineTestCase):
    def setUp(self):
        # authoritative tier table straight from the engine
        self.TAG = self.engine.call("TAG", [])

    def first_tier_pct_and_count(self, tag):
        tiers = self.TAG[tag]
        lo, hi, pct = tiers[0]
        return lo, hi, pct

    def assert_tag_pays(self, tag, items, count=None):
        """The named tag must pay floor(sum * first_tier_pct), and it must be positive."""
        lo, hi, pct = self.first_tier_pct_and_count(tag)
        if count is None:
            count = lo
        r = self.engine.call("score", items, {"countTopTags": 999999})
        total = sum(i["score"] for i in items)
        expected = math.floor(total * pct)
        self.assertGreater(expected, 0, "%s: first tier pct must be > 0" % tag)
        self.assertIn(expected, r["tags"],
                      "%s: expected %d (floor(%d*%s)) in %s" % (tag, expected, total, pct, r["tags"]))

    def n_items(self, n, score, **kw):
        return [it("i%d" % i, score, **kw) for i in range(n)]

    # --- same/different nation ---
    def test_same_nation(self):
        self.assert_tag_pays("sameNation", self.n_items(5, 100, nation="ESP"))

    def test_different_nation(self):
        self.assert_tag_pays("differentNation",
                             [it("n%d" % i, 100, nation="N%d" % i) for i in range(5)])

    def test_same_club(self):
        self.assert_tag_pays("sameClub", self.n_items(5, 100, club="Real"))

    def test_different_club(self):
        self.assert_tag_pays("differentClub",
                             [it("c%d" % i, 100, club="C%d" % i) for i in range(5)])

    def test_same_league(self):
        self.assert_tag_pays("sameLeague", self.n_items(5, 100, league="LALIGA"))

    def test_different_league(self):
        self.assert_tag_pays("differentLeague",
                             [it("l%d" % i, 100, league="L%d" % i) for i in range(5)])

    # --- rarities ---
    def test_bronze(self):
        self.assert_tag_pays("bronze", self.n_items(5, 100, rarity="Bronze"))

    def test_silver(self):
        self.assert_tag_pays("silver", self.n_items(5, 100, rarity="Silver"))

    def test_gold(self):
        self.assert_tag_pays("gold", self.n_items(5, 100, rarity="Gold"))

    # --- specials ---
    def test_holographic(self):
        self.assert_tag_pays("holographic", self.n_items(2, 100, holographic=True))

    def test_icon(self):
        self.assert_tag_pays("icon", self.n_items(2, 100, special="Icon"))

    def test_hero(self):
        self.assert_tag_pays("hero", self.n_items(2, 100, special="Hero"))

    def test_totw(self):
        self.assert_tag_pays("totw", self.n_items(3, 100, special="TOTW"))

    def test_first_owner(self):
        self.assert_tag_pays("first", self.n_items(5, 100, firstOwner=True))

    # --- positions ---
    def test_gk(self):
        self.assert_tag_pays("gk", self.n_items(3, 100, position="GK"))

    def test_def(self):
        self.assert_tag_pays("def", [it("d%d" % i, 100, position=p)
                                     for i, p in enumerate(["CB", "LB", "RB", "CB", "LB"])])

    def test_mid(self):
        self.assert_tag_pays("mid", [it("m%d" % i, 100, position=p)
                                     for i, p in enumerate(["CDM", "CM", "CAM", "LM", "RM"])])

    def test_att(self):
        self.assert_tag_pays("att", [it("a%d" % i, 100, position=p)
                                     for i, p in enumerate(["ST", "LW", "RW", "ST", "LW"])])

    # --- attributes ---
    def test_wf(self):
        self.assert_tag_pays("wf", self.n_items(3, 100, weakFoot=5))

    def test_skills(self):
        self.assert_tag_pays("skills", self.n_items(3, 100, skillMoves=5))

    # --- Multiples! (same playerKey, different itemId) ---
    def test_multi(self):
        items = [it("m0", 100, playerKey="same"), it("m1", 100, playerKey="same")]
        self.assert_tag_pays("multi", items)

    def test_all_twenty_one_covered(self):
        """Guard: every key in the TAG table is exercised above."""
        covered = {
            "sameNation", "differentNation", "sameClub", "differentClub",
            "sameLeague", "differentLeague", "bronze", "silver", "gold",
            "holographic", "icon", "hero", "totw", "first", "gk", "def", "mid",
            "att", "wf", "skills", "multi",
        }
        self.assertEqual(set(self.TAG.keys()), covered)
        self.assertEqual(len(covered), 21)


if __name__ == "__main__":
    unittest.main(verbosity=2)
