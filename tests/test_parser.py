#!/usr/bin/env python3
"""Parser tests against the offline FUT.GG fixtures (K3/K4/R2, R5).

R5 boundary: these tests assert **parse expectations only** (structure and the
frozen numbers from tests/fixtures/futgg). Engine correctness is proven
elsewhere against constructed fixtures -- never against market-dependent FUT.GG
values.

The parser lives in server.py (built once in P0; P2 only consumes it).
"""
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "futgg")


def _load_server():
    """Import server.py by path (it is a script, not an installed package)."""
    spec = importlib.util.spec_from_file_location("fc27_server", os.path.join(ROOT, "server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


srv = _load_server()


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


MALAGA_URL = "https://www.fut.gg/fut-gallery/laliga/malaga-cf/"
PL_URL = "https://www.fut.gg/fut-gallery/leagues/premier-league/"
TOTW_URL = "https://www.fut.gg/fut-gallery/rarities/totw/"


class TestPageDetection(unittest.TestCase):
    """K3: two unescaped signals; index pages carry a reason code."""

    def test_set_pages_detected(self):
        for fn, url in [("malaga_cf.html", MALAGA_URL),
                        ("premier_league.html", PL_URL),
                        ("totw.html", TOTW_URL)]:
            kind, reason = srv.detect_page(fixture(fn), url)
            self.assertEqual(kind, "set", "%s should be a set page" % fn)
            self.assertIsNone(reason)

    def test_index_pages_rejected(self):
        for fn, url in [("rarities_index.html", "https://www.fut.gg/fut-gallery/rarities/"),
                        ("premier_league_index.html", "https://www.fut.gg/fut-gallery/premier-league/"),
                        ("leagues_index.html", "https://www.fut.gg/fut-gallery/leagues/")]:
            kind, reason = srv.detect_page(fixture(fn), url)
            self.assertIsNone(kind, "%s must not be a set page" % fn)
            self.assertEqual(reason, srv.R_INDEX_PAGE)

    def test_unescape_required(self):
        """The marker check must run AFTER unescape; raw '&amp;' would fail."""
        raw = fixture("malaga_cf.html")
        self.assertIn("Grade requirements &amp; rewards", raw)
        self.assertNotIn("Grade requirements & rewards", raw)
        self.assertIn("Grade requirements & rewards", srv.unescaped(raw))

    def test_title_signal_is_singular_colon(self):
        """A plural 'FUT Gallery Sets:' title must not be treated as a set page."""
        html = ('<title>League FUT Gallery Sets: Grades &amp; Rewards | FC 27</title>'
                '<h2>Grade requirements &amp; rewards</h2>')
        kind, reason = srv.detect_page(html, "https://www.fut.gg/fut-gallery/leagues/")
        self.assertIsNone(kind)
        self.assertEqual(reason, srv.R_INDEX_PAGE)

    def test_wrong_host_rejected(self):
        kind, reason = srv.detect_page(fixture("malaga_cf.html"), "https://example.com/x")
        self.assertIsNone(kind)
        self.assertEqual(reason, srv.R_NOT_FUTGG)

    def test_set_title_without_marker_rejected(self):
        html = '<title>Foo FUT Gallery Set: X | FC 27</title><p>nothing here</p>'
        kind, reason = srv.detect_page(html, "https://www.fut.gg/fut-gallery/x/foo/")
        self.assertIsNone(kind)
        self.assertEqual(reason, srv.R_NO_GRADE_TABLE)


class TestGradeTable(unittest.TestCase):
    """K4/H6: row-based parsing, reward only via a gallery-token image."""

    def test_malaga_thresholds_and_rewards(self):
        d = srv.parse_futgg(fixture("malaga_cf.html"), MALAGA_URL)
        self.assertEqual(d["thresholds"], {"D": 10, "C": 300, "B": 400, "A": 700, "S": 900})
        self.assertEqual(d["rewards"], {"D": 0, "C": 0, "B": 5, "A": 8, "S": 15})
        self.assertEqual(sum(d["rewards"].values()), 28)

    def test_malaga_badge_kit_are_zero_with_text(self):
        """H6: D/C rewards are Badge/Kit -> reward 0 + rewardText."""
        d = srv.parse_futgg(fixture("malaga_cf.html"), MALAGA_URL)
        self.assertEqual(d["rewards"]["D"], 0)
        self.assertEqual(d["rewards"]["C"], 0)
        self.assertIn("Badge", d["rewardText"]["D"])
        self.assertIn("Kit", d["rewardText"]["C"])

    def test_premier_league_thresholds_and_rewards(self):
        d = srv.parse_futgg(fixture("premier_league.html"), PL_URL)
        self.assertEqual(d["thresholds"],
                         {"D": 10, "C": 400000, "B": 800000, "A": 1900000, "S": 4000000})
        self.assertEqual(d["rewards"], {"D": 10, "C": 35, "B": 50, "A": 70, "S": 100})
        self.assertEqual(sum(d["rewards"].values()), 265)

    def test_comma_separated_thresholds(self):
        """Thousands separators ('400,000') must be normalised to ints."""
        d = srv.parse_futgg(fixture("premier_league.html"), PL_URL)
        for g in "DCBAS":
            self.assertIsInstance(d["thresholds"][g], int)
        self.assertEqual(d["thresholds"]["A"], 1900000)

    def test_totw_thresholds_and_rewards(self):
        d = srv.parse_futgg(fixture("totw.html"), TOTW_URL)
        self.assertEqual(d["thresholds"],
                         {"D": 10, "C": 125000, "B": 175000, "A": 300000, "S": 550000})
        self.assertEqual(d["rewards"], {"D": 5, "C": 15, "B": 30, "A": 50, "S": 75})
        self.assertEqual(sum(d["rewards"].values()), 175)

    def test_reward_requires_token_image(self):
        """A row without a gallery-token image must yield reward 0."""
        row_no_token = ('<tr data-gallery-reward="B"><td>B</td>'
                        '<td>400</td><td><img alt="Club Badge"/>Club Badge</td></tr>')
        t = srv.parse_grade_table(row_no_token)
        self.assertEqual(t["B"]["reward"], 0)
        self.assertIn("Badge", t["B"]["rewardText"])


class TestSlotsEligibility(unittest.TestCase):
    """K4: slots cascade (description -> body -> oracle) + eligibility typing."""

    def test_malaga_slots_from_description(self):
        d = srv.parse_futgg(fixture("malaga_cf.html"), MALAGA_URL)
        self.assertEqual(d["slots"], 15)
        self.assertFalse(d["slotsEstimated"])
        self.assertEqual(d["slotsSource"], "description")

    def test_malaga_eligibility_club_men(self):
        """K4 abortion evidence: description says 'Malaga CF Mens players'
        -> eligibility {type: club, value: Malaga CF, gender: men}."""
        raw = fixture("malaga_cf.html")
        # the source sentence the parser must read (from the meta description)
        self.assertIn("Requires 15 Malaga CF Mens players to complete",
                      srv.meta_description(raw))
        d = srv.parse_futgg(raw, MALAGA_URL)
        self.assertEqual(d["eligibility"]["type"], "club")
        self.assertEqual(d["eligibility"]["value"], "Malaga CF")
        self.assertEqual(d["eligibility"]["gender"], "men")

    def test_premier_league_slots_and_type(self):
        d = srv.parse_futgg(fixture("premier_league.html"), PL_URL)
        self.assertEqual(d["slots"], 30)
        self.assertFalse(d["slotsEstimated"])
        self.assertEqual(d["eligibility"]["type"], "league")
        self.assertEqual(d["eligibility"]["value"], "Premier League")

    def test_totw_slots_estimated_from_oracle(self):
        d = srv.parse_futgg(fixture("totw.html"), TOTW_URL)
        self.assertEqual(d["slots"], 20)
        self.assertTrue(d["slotsEstimated"])
        self.assertEqual(d["slotsSource"], "oracle")

    def test_totw_eligibility_rarity(self):
        d = srv.parse_futgg(fixture("totw.html"), TOTW_URL)
        self.assertEqual(d["eligibility"]["type"], "rarity")
        self.assertEqual(d["eligibility"]["value"], "TOTW")
        self.assertEqual(d["eligibility"]["gender"], "any")

    def test_parse_requirements_numbered(self):
        slots, scope, gender = srv.parse_requirements("Requires 15 Malaga CF Mens players to complete")
        self.assertEqual(slots, 15)
        self.assertEqual(gender, "men")

    def test_parse_requirements_numberless(self):
        slots, scope, gender = srv.parse_requirements("Requires Team of the Week players to complete")
        self.assertIsNone(slots)
        self.assertEqual(scope, "Team of the Week")

    def test_parse_requirements_ignores_rsc_blob(self):
        """The embedded JSON tag descriptions must not be read as the requirement."""
        blob = ('Requires players from the same nation.",priority:1,color:"#8B9AC2"},'
                'Requires players from different nations.",priority:2}')
        slots, scope, gender = srv.parse_requirements(blob)
        self.assertIsNone(slots, "sentence fragments in the RSC blob must not yield a slot count")

    def test_women_gender(self):
        _, _, gender = srv.parse_requirements("Requires 15 Birmingham City Women's players to complete")
        self.assertEqual(gender, "women")


class TestParseErrors(unittest.TestCase):
    """Non-set inputs raise ValueError with the machine-readable reason."""

    def test_index_page_raises(self):
        with self.assertRaises(ValueError) as cm:
            srv.parse_futgg(fixture("rarities_index.html"), "https://www.fut.gg/fut-gallery/rarities/")
        self.assertEqual(str(cm.exception), srv.R_INDEX_PAGE)

    def test_no_grade_table_raises(self):
        html = ('<title>Foo FUT Gallery Set: X | FC 27</title>'
                '<h2>Grade requirements &amp; rewards</h2><p>no rows</p>')
        with self.assertRaises(ValueError) as cm:
            srv.parse_futgg(html, "https://www.fut.gg/fut-gallery/x/foo/")
        self.assertEqual(str(cm.exception), srv.R_NO_GRADE_TABLE)


class TestParseShape(unittest.TestCase):
    """The returned object keeps the app's gallery shape."""

    def test_keys_and_id(self):
        d = srv.parse_futgg(fixture("malaga_cf.html"), MALAGA_URL)
        for k in ("id", "name", "slots", "slotsEstimated", "eligibility",
                  "thresholds", "rewards", "sourceUrl"):
            self.assertIn(k, d)
        self.assertEqual(d["id"], "malaga_cf")
        self.assertEqual(d["name"], "Malaga CF")
        self.assertEqual(d["sourceUrl"], MALAGA_URL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
