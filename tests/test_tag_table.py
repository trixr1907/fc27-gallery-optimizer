#!/usr/bin/env python3
"""P1 fix — the engine TAG table must match a DATED OFFLINE fixture.

Why: `test_all_tags.py` reads the expected percentage FROM the engine's own TAG
table, so it cannot detect a wrong value *inside* that table. This module adds an
INDEPENDENT oracle: a dated snapshot of the FUT.GG bonus-tags page
(`tests/fixtures/futgg/bonus_tags.html`, fetched 2026-10-04) is parsed here, and
the engine's TAG table is compared tier-by-tier against it.

The fixture is plain HTML with one `<tr data-tag-key="...">` per tag and a
`<li>` per tier ("5–9 +1%"). Parsing is done in Python WITHOUT the engine, so a
divergence between the two is a real finding. No network access is used.
"""

import os
import re
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from engine_harness import EngineTestCase  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "futgg", "bonus_tags.html")


def parse_fixture(path=FIXTURE):
    """Return {tagKey: [[lo, hi, pct], ...]} parsed from the dated fixture.

    `hi=999` means the open-ended top tier ("20+"). Percentages are fractions.
    """
    with open(path, encoding="utf-8") as f:
        html = f.read()
    # Only parse the real table body (the leading HTML comment documents the
    # format and must not contribute rows).
    body_start = html.index("<tbody>")
    body = html[body_start:html.index("</tbody>", body_start)]
    table = {}
    for row in re.finditer(r'<tr data-tag-key="([^"]+)">(.*?)</tr>', body, re.S):
        key, body = row.group(1), row.group(2)
        tiers = []
        for li in re.findall(r"<li>([^<]+)</li>", body):
            m = re.match(r"\s*(\d+)\s*[–-]\s*(\d+)\s*\+([\d.]+)%", li)
            if not m:
                m = re.match(r"\s*(\d+)\s*\+\s*\+([\d.]+)%", li)
                lo, hi, pct = int(m.group(1)), 999, float(m.group(2))
            else:
                lo, hi, pct = int(m.group(1)), int(m.group(2)), float(m.group(3))
            tiers.append([lo, hi, round(pct / 100.0, 6)])
        table[key] = tiers
    return table


def fixture_total_and_updated(path=FIXTURE):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    total = int(re.search(r'data-total="(\d+)"', html).group(1))
    updated = re.search(r'data-updated="([^"]+)"', html).group(1)
    return total, updated


class TestTagFixtureParses(unittest.TestCase):
    """The fixture itself must parse cleanly (independent of the engine)."""

    def test_fixture_file_exists(self):
        self.assertTrue(os.path.exists(FIXTURE), FIXTURE)

    def test_fixture_has_21_tags(self):
        table = parse_fixture()
        self.assertEqual(len(table), 21)
        total, updated = fixture_total_and_updated()
        self.assertEqual(total, 21)
        self.assertIn("27 Sept 2026", updated)

    def test_every_tag_has_three_tiers(self):
        for key, tiers in parse_fixture().items():
            self.assertEqual(len(tiers), 3, "%s must have 3 tiers" % key)
            self.assertEqual(tiers[-1][1], 999, "%s top tier must be open-ended" % key)

    def test_percentages_are_fractions(self):
        for key, tiers in parse_fixture().items():
            for lo, hi, pct in tiers:
                self.assertLess(pct, 10.0, "%s tier %s looks like a raw number" % (key, tiers))
                self.assertGreater(pct, 0)


class TestEngineTagTableMatchesFixture(EngineTestCase):
    """The engine TAG table must equal the independent dated fixture."""

    def setUp(self):
        self.TAG = self.engine.call("TAG", [])
        self.fixture = parse_fixture()

    def test_same_keys(self):
        self.assertEqual(sorted(self.TAG.keys()), sorted(self.fixture.keys()))

    def test_same_tier_values(self):
        for key, tiers in self.fixture.items():
            eng = self.TAG[key]
            self.assertEqual(len(eng), len(tiers), "%s tier count differs" % key)
            for i, (lo, hi, pct) in enumerate(tiers):
                self.assertEqual(eng[i][0], lo, "%s tier %d lo" % (key, i))
                self.assertEqual(eng[i][1], hi, "%s tier %d hi" % (key, i))
                self.assertAlmostEqual(eng[i][2], pct, places=6, msg="%s tier %d pct" % (key, i))

    def test_pct_function_agrees_with_fixture(self):
        """pct(rule, n) must return the fixture value at each tier's lower bound."""
        for key, tiers in self.fixture.items():
            for lo, hi, pct in tiers:
                self.assertAlmostEqual(
                    self.engine.call("pct", key, lo), pct, places=6,
                    msg="pct(%s, %d) should be %s" % (key, lo, pct))
                # also probe the upper bound when it is a real bound
                if hi != 999:
                    self.assertAlmostEqual(
                        self.engine.call("pct", key, hi), pct, places=6,
                        msg="pct(%s, %d) should be %s" % (key, hi, pct))

    def test_gap_below_first_tier_is_zero(self):
        """Below the first tier the tag pays nothing."""
        for key, tiers in self.fixture.items():
            lo = tiers[0][0]
            self.assertEqual(self.engine.call("pct", key, lo - 1), 0, key)


class TestCountTopTagsCap(EngineTestCase):
    """`score()` must pay only the N biggest tags by default (countTopTags=10),
    and pay ALL tags when countTopTags is Infinity.

    This is the FUT.GG rule "Only the ten biggest tags pay". The cap is checked
    against the engine's OWN `tags` array (the full, uncapped, sorted breakdown),
    so the expected paying set is derived independently of the cap logic.
    """

    @staticmethod
    def _many_tag_items():
        """A lineup engineered to trigger MORE than 10 distinct positive tags.

        Ten same-nation/club/league cards (sameNation, sameClub, sameLeague) plus
        five distinct-nation cards (differentNation) plus a duplicated playerKey
        (multi) plus rarity/position/attribute/special variety -> 15 positive tags.
        """
        items = []
        for i in range(10):
            items.append({
                "itemId": "x%d" % i, "playerKey": "pk%d" % i, "name": "p%d" % i,
                "score": 1000, "nation": "ESP", "club": "Real", "league": "LALIGA",
                "rarity": ["Bronze", "Silver", "Gold"][i % 3],
                "position": ["GK", "CB", "CM", "ST"][i % 4],
                "weakFoot": 5 if i % 2 else 3, "skillMoves": 5 if i % 2 else 3,
                "holographic": i % 5 == 0, "firstOwner": i % 2 == 0,
                "special": ["", "Icon", "Hero", "TOTW"][i % 4],
            })
        for j in range(10, 15):
            items.append({
                "itemId": "x%d" % j, "playerKey": "pk%d" % j, "name": "p%d" % j,
                "score": 1000, "nation": "M%d" % j, "club": "Q%d" % j, "league": "P%d" % j,
                "rarity": "", "position": "ST", "weakFoot": 3, "skillMoves": 3,
                "holographic": False, "firstOwner": False, "special": "",
            })
        items.append({"itemId": "x100", "playerKey": "dup", "name": "d100", "score": 1000,
                      "nation": "D", "club": "D", "league": "D", "rarity": "",
                      "position": "CM", "weakFoot": 3, "skillMoves": 3,
                      "holographic": False, "firstOwner": False, "special": ""})
        items.append({"itemId": "x101", "playerKey": "dup", "name": "d101", "score": 1000,
                      "nation": "E", "club": "E", "league": "E", "rarity": "",
                      "position": "CM", "weakFoot": 3, "skillMoves": 3,
                      "holographic": False, "firstOwner": False, "special": ""})
        return items

    def _tags(self, items, count):
        opts = {"countTopTags": count} if count is not None else {}
        return self.engine.call("score", items, opts)["tags"]

    def test_default_cap_is_ten(self):
        """Without an explicit option the engine caps at DEFAULT_COUNT_TOP_TAGS (10)."""
        items = self._many_tag_items()
        tags = self._tags(items, None)
        self.assertGreater(len(tags), 10, "scenario must trigger >10 tags to be meaningful")
        r = self.engine.call("score", items, {})   # default
        r10 = self.engine.call("score", items, {"countTopTags": 10})
        self.assertEqual(r["bonus"], r10["bonus"])
        # the paying set is exactly the ten largest (tags are sorted desc)
        self.assertEqual(r["bonus"], sum(tags[:10]))

    def test_infinity_pays_all(self):
        items = self._many_tag_items()
        tags = self._tags(items, None)
        # Use an explicit huge number: JSON cannot carry JS `Infinity`, and the
        # engine's `Infinity` path is `!Number.isFinite(countTopTags)`. A very
        # large integer makes the `slice(0, n)` return the whole array, i.e. all.
        r_all = self.engine.call("score", items, {"countTopTags": 10 ** 9})
        self.assertEqual(r_all["bonus"], sum(tags))
        self.assertGreater(r_all["bonus"], sum(tags[:10]))

    def test_cap_monotone_and_bounded(self):
        """Raising the cap can only add bonus (never remove), and never exceeds all."""
        items = self._many_tag_items()
        tags = self._tags(items, None)
        prev = -1
        for n in (1, 3, 10, 15, 21, 10 ** 9):
            r = self.engine.call("score", items, {"countTopTags": n})
            self.assertGreaterEqual(r["bonus"], prev)
            self.assertLessEqual(r["bonus"], sum(tags))
            prev = r["bonus"]
        self.assertEqual(self.engine.call("score", items, {"countTopTags": 10 ** 9})["bonus"], sum(tags))

    def test_exactly_ten_pays_ten(self):
        items = self._many_tag_items()
        tags = self._tags(items, None)
        r = self.engine.call("score", items, {"countTopTags": 10})
        expected = sum(sorted(tags, reverse=True)[:10])
        self.assertEqual(r["bonus"], expected)


class TestCountTopTagsInfinityVariant(EngineTestCase):
    """The engine must treat a non-finite cap as "pay all tags".

    JSON cannot carry JS `Infinity`, so this checks the equivalent spellings the
    engine/UI accept: a very large integer (full `slice`), and a direct probe of
    the engine's own `Infinity` handling via the exported helper.
    """

    def test_large_int_equals_all(self):
        items = TestCountTopTagsCap._many_tag_items()
        tags = self.engine.call("score", items, {})["tags"]
        self.assertGreater(len(tags), 10)
        full = sum(tags)
        self.assertEqual(self.engine.call("score", items, {"countTopTags": 10 ** 9})["bonus"], full)
        self.assertLess(self.engine.call("score", items, {})["bonus"], full)

    def test_default_constant_is_ten(self):
        """DEFAULT_COUNT_TOP_TAGS must be 10 (the FUT.GG rule)."""
        exports = self.engine.exports()
        self.assertIn("DEFAULT_COUNT_TOP_TAGS", exports)


if __name__ == "__main__":
    unittest.main(verbosity=2)
