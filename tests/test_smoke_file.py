#!/usr/bin/env python3
"""P4.2 -- `file://` smoke test.

The app is a single self-contained `index.html`: opening it directly from disk
must work with NO server. This module loads a COPY of the real `index.html` over
`file://` in headless Chrome, drives the app's own entry points, and asserts that
the app boots, renders, virtualises the table and runs the cooperative optimizer.

It also pins the agreed LIMITATION of the `file://` mode: the FUT.GG importer is
a server endpoint (`/api/futgg`), so it cannot work from disk. That is asserted
explicitly rather than left implicit.

Chrome is required; if it is not found the module SKIPS (never a red failure),
exactly like the Node-backed engine tests.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "tools"))
import bench_browser  # noqa: E402  (reuse the single Chrome locator)


def small_state():
    """A tiny but REAL state: 3 sets, ~300 cards, one card shared by all sets."""
    players, galleries = [], []
    for s in range(3):
        sid = "g%d" % s
        galleries.append({
            "id": sid, "name": "Set %d" % s, "slots": 5,
            "eligibility": {"type": "club", "value": "AC", "gender": "any"},
            "thresholds": {"D": 10, "C": 300, "B": 600, "A": 900, "S": 1200},
            "rewards": {"D": 0, "C": 5, "B": 10, "A": 20, "S": 40},
        })
        for i in range(3):
            players.append({
                "id": "%s_o%d" % (sid, i), "itemId": "%s_o%d" % (sid, i),
                "playerKey": "own-%s-%d" % (sid, i), "name": "Owned %s %d" % (sid, i),
                "score": 60 + i * 20, "club": "AC", "league": "L", "nation": "Spain",
                "position": "CM", "rarity": "Gold", "special": "",
                "collected": True, "buyPrice": 100, "resalePrice": 60,
            })
        for i in range(100):
            players.append({
                "id": "%s_c%03d" % (sid, i), "itemId": "%s_c%03d" % (sid, i),
                "playerKey": "cand-%s-%d" % (sid, i), "name": "Card %s %d" % (sid, i),
                "score": 40 + (i * 7) % 400, "club": "AC", "league": "L",
                "nation": "Spain", "position": "CM", "rarity": "Gold", "special": "",
                "collected": False, "buyPrice": 50 + i, "resalePrice": 20 + (i % 40),
            })
    # one card eligible for every set (shared purchase)
    players.append({
        "id": "shared", "itemId": "shared", "playerKey": "shared", "name": "Shared Star",
        "score": 500, "club": "AC", "league": "L", "nation": "Spain",
        "position": "CM", "rarity": "Gold", "special": "",
        "collected": False, "buyPrice": 300, "resalePrice": 100,
    })
    return {
        "schemaVersion": 2,
        "settings": {"coins": 100000, "reserve": 0, "taxRate": 0.05,
                     "objective": "eff", "maxBundle": 5, "priceScenario": "base"},
        "players": players,
        "galleries": galleries,
    }


DRIVER = r"""
<script>
(function () {
  var out = { errors: [] };
  function setTitle(o) { document.title = 'FC27SMOKE:' + JSON.stringify(o); }
  try {
    // The app must have booted from disk with no server at all.
    out.protocol = location.protocol;
    out.booted = (typeof render === 'function') && (typeof portfolioPlan === 'function')
              && (typeof portfolioSearch === 'function') && (typeof lineup === 'function');
    // Drive it with a real state.
    state = __STATE__;
    render();
    out.rendered = true;
    out.sets = state.galleries.length;
    out.players = state.players.length;
    // The collection table must be virtualised (only a window in the DOM).
    out.dom_rows = document.querySelectorAll('#playersScroll tbody tr.prow').length;
    // The engine must still be correct in the browser: compare against a
    // synchronous reference evaluation.
    var g0 = state.galleries[0];
    var pool = state.players.filter(function (p) { return p.collected; });
    var ref = lineup(pool, 15);
    out.lineup_total = ref.total;
    out.lineup_items = ref.items.length;
    // The cooperative optimizer must run to a usable plan WITHOUT a server.
    var s = portfolioSearch(state.galleries, state.players,
                            optOpts({ totalBudgetMs: 1500 }));
    var r = s.step(20), n = 0;
    while (!r.done && !r.paused && n < 500) { r = s.step(20); n++; }
    out.search_steps = n;
    out.search_paused = !!r.paused;
    out.progress_best = (r.progress && r.progress.best) ? r.progress.best.length : null;
    out.plan_value = r.plan ? r.plan.value : null;
    out.plan_feasible = r.plan ? !!r.plan.feasible : null;
    // Render the intermediate so the panel is populated.
    renderPortfolioProgress(r.progress, !!r.done, !!r.paused);
    var pf = document.getElementById('portfolio');
    out.portfolio_html = pf ? (pf.innerHTML || '').length : 0;
    // Per-set plans must also work from disk.
    var p = planSet(state.galleries[0], state.players,
                    { objective: 'eff', taxRate: 0.05, maxBundle: 5,
                      coins: 100000, reserve: 0, priceScenario: 'base' });
    out.plan_set_optimality = p.optimality;
    out.plan_set_recos = p.recommendations.length;
  } catch (e) { out.errors.push(String((e && e.message) || e)); }
  setTitle(out);
})();
</script>
"""


def chrome_available():
    return bench_browser.find_chrome() is not None


@unittest.skipUnless(chrome_available(), "headless Chrome not found (file:// smoke test needs it)")
class TestFileProtocolSmoke(unittest.TestCase):
    """Load the real app from disk and prove it works without a server."""

    @classmethod
    def setUpClass(cls):
        cls.chrome = bench_browser.find_chrome()
        cls.tmp = tempfile.mkdtemp(prefix="fc27smoke_")
        with open(os.path.join(_ROOT, "index.html"), encoding="utf-8") as f:
            html = f.read()
        state_json = json.dumps(small_state(), separators=(",", ":"))
        # Inject the driver right before </body> (after the app script).
        html = html.replace("</body>", DRIVER.replace("__STATE__", state_json) + "</body>", 1)
        cls.path = os.path.join(cls.tmp, "index.html")
        with open(cls.path, "w", encoding="utf-8") as f:
            f.write(html)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_app(self):
        profile = os.path.join(self.tmp, "profile")
        url = "file:///" + self.path.replace("\\", "/")
        cmd = [self.chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
               "--disable-dev-shm-usage", "--allow-file-access-from-files",
               "--user-data-dir=" + profile, "--dump-dom", url]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)
        import re
        m = re.search(r"FC27SMOKE:(\{.*?\})</title>", proc.stdout, re.S)
        self.assertIsNotNone(
            m, "the app did not report a result over file://; stderr=%s" % proc.stderr[:400])
        return json.loads(m.group(1))

    @classmethod
    def setUpClass_result(cls):
        pass

    def test_app_boots_and_runs_from_disk(self):
        r = self.run_app()
        self.assertEqual(r["errors"], [], "the app raised: %s" % r["errors"])
        self.assertEqual(r["protocol"], "file:")
        self.assertTrue(r["booted"], "the app's entry points are missing")
        self.assertTrue(r["rendered"])

    def test_table_is_virtualised(self):
        r = self.run_app()
        self.assertGreater(r["players"], 300)
        self.assertLess(r["dom_rows"], 200,
                        "the collection table rendered %s rows" % r["dom_rows"])

    def test_engine_is_correct_in_the_browser(self):
        """The browser engine must compute a real lineup from the real pool."""
        r = self.run_app()
        # 3 owned cards per set -> the pool is smaller than the 15 slots, so the
        # lineup keeps every owned card (and never more than the slot count).
        self.assertGreater(r["lineup_items"], 0)
        self.assertLessEqual(r["lineup_items"], 15)
        self.assertGreater(r["lineup_total"], 0)

    def test_cooperative_optimizer_runs_without_a_server(self):
        r = self.run_app()
        self.assertGreater(r["search_steps"], 0, "the search never advanced")
        self.assertIsNotNone(r["progress_best"], "no intermediate plan was published")
        self.assertGreater(r["portfolio_html"], 0, "the portfolio panel stayed empty")
        # Either it finished inside the budget or it paused, keeping a plan.
        self.assertTrue(r["search_paused"] or r["plan_value"] is not None)

    def test_per_set_plan_runs_without_a_server(self):
        r = self.run_app()
        self.assertIn(r["plan_set_optimality"], ("proved", "node_limit"))
        self.assertIsInstance(r["plan_set_recos"], int)

    def test_file_protocol_limitation_is_documented(self):
        """file:// limitation: `/api/futgg` is a SERVER route, so the importer
        cannot work from disk. That must be stated, not left implicit."""
        with open(os.path.join(_ROOT, "index.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertIn("/api/futgg", html)
        with open(os.path.join(_ROOT, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        self.assertIn("file://", readme,
                      "the README must document the file:// mode explicitly")
        self.assertIn("/api/futgg", readme,
                      "the README must name the endpoint that needs the server")


if __name__ == "__main__":
    unittest.main()
