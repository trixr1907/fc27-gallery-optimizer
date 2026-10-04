#!/usr/bin/env python3
"""F1-rev -- score() and bonus() correctness, proven against the REAL engine.

Coverage (all from the approved plan):
  1. Unit contract `bonus(matchedItems, pct) = floor(sum(scores) * pct)` with the
     six oracle bands.
  2. Three constructible micro-fixtures, each with every NON-target tag asserted 0:
       * Attack      : 5 attackers, sum 168 -> All out Attack = 5
       * Midfield    : 10 midfielders, sum 401 -> Midfield Control = 24
         Midfield+Silver: 5 Silver of them, sum 168 -> Silver = 25
       * Truncation  : exactly 12 active tags -> countTopTags=10 drops the 2 smallest
  3. Property: total - base == sum(tag floors after the top-N cut); bonus >= 0;
     bonus == 0 when no tag reaches a tier.

R5: inputs are CONSTRUCTED here, not read from FUT.GG market data. The engine is
the real JS engine, driven through tools/engine_cli.js.
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from engine_harness import EngineTestCase  # noqa: E402


def item(iid, score, *, nation="N", club="K", league="G", rarity="", position="CM",
         player_key=None, weak_foot=3, skill_moves=3, holographic=False,
         first_owner=False, special=""):
    """Build one engine item dict with explicit, fully-specified fields."""
    return {
        "itemId": iid, "playerKey": player_key or ("pk-" + iid), "name": iid,
        "score": score, "nation": nation, "club": club, "league": league,
        "rarity": rarity, "position": position, "weakFoot": weak_foot,
        "skillMoves": skill_moves, "holographic": holographic,
        "firstOwner": first_owner, "special": special,
    }


class TestBonusUnitBands(EngineTestCase):
    """F1-rev (1): bonus(matchedItems, pct) with the six oracle bands."""

    def test_band_13(self):
        """floor(650*.02)=13 and floor(699*.02)=13."""
        self.assertEqual(self.engine.call("bonus", [{"score": 650}], 0.02), 13)
        self.assertEqual(self.engine.call("bonus", [{"score": 699}], 0.02), 13)

    def test_band_14(self):
        """floor(700*.02)=14."""
        self.assertEqual(self.engine.call("bonus", [{"score": 700}], 0.02), 14)
        self.assertEqual(self.engine.call("bonus", [{"score": 749}], 0.02), 14)

    def test_band_126(self):
        """floor(420*.30)=126 and floor(423*.30)=126."""
        self.assertEqual(self.engine.call("bonus", [{"score": 420}], 0.30), 126)
        self.assertEqual(self.engine.call("bonus", [{"score": 423}], 0.30), 126)

    def test_band_5(self):
        """floor(167*.03)=5 and floor(199*.03)=5."""
        self.assertEqual(self.engine.call("bonus", [{"score": 167}], 0.03), 5)
        self.assertEqual(self.engine.call("bonus", [{"score": 199}], 0.03), 5)

    def test_band_24(self):
        """floor(400*.06)=24 and floor(416*.06)=24."""
        self.assertEqual(self.engine.call("bonus", [{"score": 400}], 0.06), 24)
        self.assertEqual(self.engine.call("bonus", [{"score": 416}], 0.06), 24)

    def test_band_12(self):
        """floor(400*.03)=12 and floor(433*.03)=12."""
        self.assertEqual(self.engine.call("bonus", [{"score": 400}], 0.03), 12)
        self.assertEqual(self.engine.call("bonus", [{"score": 433}], 0.03), 12)

    def test_pl_same_league_oracle_22335(self):
        """Same League, 30 items, +8% -> floor(sum*.08)=22335 for sum in [279188,279199].

        NOTE: this is a *dated snapshot* value (see plan). It is only used to pin
        the arithmetic contract, never as a stable FUT.GG assertion.
        """
        self.assertEqual(self.engine.call("bonus", [{"score": 279188}], 0.08), 22335)
        self.assertEqual(self.engine.call("bonus", [{"score": 279199}], 0.08), 22335)

    def test_contract_sums_item_list_itself(self):
        """bonus() receives a list and sums it -- three ways to reach 650 agree."""
        self.assertEqual(self.engine.call("bonus", [{"score": 325}, {"score": 325}], 0.02), 13)
        self.assertEqual(self.engine.call("bonus", [{"score": 650}], 0.02), 13)
        self.assertEqual(
            self.engine.call("bonus", [{"score": 100}, {"score": 200}, {"score": 350}], 0.02), 13)

    def test_zero_pct_is_zero(self):
        self.assertEqual(self.engine.call("bonus", [{"score": 999}], 0), 0)


class TestAttackFixture(EngineTestCase):
    """F1-rev (2a): 5 attackers, sum 168 -> only All out Attack pays 5."""

    def _items(self):
        # ST/LW/RW x5, sum 34+34+34+33+33 = 168. All non-target tags kept at 0:
        # no rarity tier, nations/clubs/leagues reused in groups <= 4 and <= 4 distinct.
        return [
            item("a1", 34, nation="N1", club="K1", league="G1", position="ST"),
            item("a2", 34, nation="N2", club="K2", league="G2", position="LW"),
            item("a3", 34, nation="N3", club="K3", league="G3", position="RW"),
            item("a4", 33, nation="N4", club="K4", league="G4", position="ST"),
            item("a5", 33, nation="N4", club="K4", league="G4", position="LW"),
        ]

    def test_all_out_attack_pays_5(self):
        r = self.engine.call("score", self._items(), {"countTopTags": 10})
        self.assertEqual(r["base"], 168)
        self.assertEqual(r["bonus"], 5)
        self.assertEqual(r["tags"], [5])

    def test_every_non_target_tag_is_zero(self):
        """The explicit zero-assertion the plan requires for the Attack fixture."""
        r = self.engine.call("score", self._items(), {"countTopTags": 10})
        # Only one tag may pay, and it must be exactly 5.
        self.assertEqual(len(r["tags"]), 1)
        self.assertEqual(r["tags"][0], 5)


class TestMidfieldFixtures(EngineTestCase):
    """F1-rev (2b): Midfield Control = 24; Silver = 25 (NOT the 10-19 tier 30)."""

    def _midfield_only(self):
        # 10 midfielders (CM), sum 41 + 40*9 = 401; nations/clubs/leagues from a
        # pool of 4 (=> distinct 4 < 5, groups <= 3 < 5 => all those tags 0).
        items = []
        for i, s in enumerate([41, 40, 40, 40, 40, 40, 40, 40, 40, 40]):
            k = i % 4
            items.append(item("m%d" % i, s, nation="MN%d" % k, club="MK%d" % k,
                              league="MG%d" % k, position="CM"))
        return items

    def _midfield_silver(self):
        # 12 items: 10 midfielders = 5 Silver (sum 168) + 5 non-silver (sum 233);
        # + 2 defenders to fill slots. Keys from a pool of 4, each used 3x.
        raw = []
        for i, s in enumerate([34, 34, 33, 34, 33]):
            raw.append(("s%d" % i, s, "Silver", "CM"))
        for i, s in enumerate([47, 47, 47, 46, 46]):
            raw.append(("n%d" % i, s, "", "CM"))
        raw.append(("d1", 50, "", "CB"))
        raw.append(("d2", 50, "", "CB"))
        items = []
        for j, (iid, s, rar, pos) in enumerate(raw):
            k = j % 4
            items.append(item(iid, s, nation="MN%d" % k, club="MK%d" % k,
                              league="MG%d" % k, rarity=rar, position=pos))
        return items

    def test_midfield_control_24(self):
        r = self.engine.call("score", self._midfield_only(), {"countTopTags": 10})
        self.assertEqual(r["tags"], [24], "only Midfield Control may pay (24)")
        self.assertEqual(r["bonus"], 24)

    def test_midfield_silver_25_not_30(self):
        """5 Silver, sum 168 -> tier 5-9 (+15%) = 25; the 10-19 tier (30) must NOT apply."""
        r = self.engine.call("score", self._midfield_silver(), {"countTopTags": 10})
        self.assertEqual(r["tags"], [25, 24], "Silver=25 and Midfield=24, nothing else")
        self.assertNotIn(30, r["tags"], "Silver must not take the 10-19 tier")
        self.assertEqual(r["bonus"], 49)


class TestTopTenTruncation(EngineTestCase):
    """F1-rev (2c): with exactly 12 active tags, countTopTags=10 drops the 2 smallest."""

    def _items(self):
        positions = ["GK", "CB", "LB", "RB", "CDM", "CM", "CAM", "LM", "RM", "ST",
                     "LW", "RW", "GK", "CB", "LB", "RB", "CDM", "CM", "ST", "RW"]
        items = []
        for i, pos in enumerate(positions):
            items.append(item("t%d" % i, 100, nation="NATION", club="CLUB",
                              league="LEAGUE", position=pos, weak_foot=5,
                              skill_moves=5, holographic=True, first_owner=True,
                              special="TOTW"))
        # Force Multiples! as the 12th distinct tag (two cards, one playerKey).
        items[0]["playerKey"] = "dup"
        items[1]["playerKey"] = "dup"
        return items

    def test_exactly_twelve_active_tags(self):
        r = self.engine.call("score", self._items(), {"countTopTags": 999999})
        self.assertEqual(len(r["tags"]), 12, "fixture must activate exactly 12 tags")

    def test_top10_drops_the_two_smallest(self):
        items = self._items()
        r10 = self.engine.call("score", items, {"countTopTags": 10})
        rinf = self.engine.call("score", items, {"countTopTags": 999999})
        smallest_two = sum(sorted(rinf["tags"])[:2])
        self.assertEqual(rinf["bonus"] - r10["bonus"], smallest_two)
        self.assertEqual(r10["bonus"], sum(sorted(rinf["tags"], reverse=True)[:10]))

    def test_infinity_equals_all(self):
        items = self._items()
        r_inf = self.engine.call("score", items, {"countTopTags": 999999})
        self.assertEqual(r_inf["bonus"], sum(r_inf["tags"]))


class TestProperties(EngineTestCase):
    """F1-rev (3): engine-internal invariants (no oracle needed)."""

    def _seeded_sets(self):
        # A few deterministic, varied sets.
        return [
            [item("p%d" % i, 100 + i, nation="X%d" % (i % 3), club="Y%d" % (i % 4),
                  league="Z%d" % (i % 2), position=["ST", "CM", "CB", "GK"][i % 4])
             for i in range(9)],
            [item("q%d" % i, 60, position="ST") for i in range(6)],
            [item("r0", 200, rarity="Gold"), item("r1", 200, rarity="Gold")],
        ]

    def test_total_minus_base_equals_sum_of_paying_tags(self):
        for items in self._seeded_sets():
            for n in (10, 999999):
                r = self.engine.call("score", items, {"countTopTags": n})
                self.assertEqual(r["total"] - r["base"], r["bonus"])
                self.assertEqual(r["bonus"], sum(r["tags"]))
                self.assertEqual(r["base"], sum(i["score"] for i in items))

    def test_bonus_non_negative(self):
        for items in self._seeded_sets():
            r = self.engine.call("score", items, {"countTopTags": 10})
            self.assertGreaterEqual(r["bonus"], 0)

    def test_bonus_zero_when_no_tier_reached(self):
        """Two items with everything distinct -> no tag reaches a tier."""
        items = [item("z0", 50, nation="A", club="B", league="C", position="ST"),
                 item("z1", 50, nation="D", club="E", league="F", position="CB")]
        r = self.engine.call("score", items, {"countTopTags": 10})
        self.assertEqual(r["tags"], [])
        self.assertEqual(r["bonus"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
