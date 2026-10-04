#!/usr/bin/env python3
"""K1 harness smoke -- the real JS engine is reachable and non-empty.

Covers the two execution paths required by R1:

  * Node path      -- tools/engine_cli.js requires engine/engine.js and returns
                      results over the JSON-Lines batch protocol.
  * Browser path   -- the same source evaluated with `module === undefined`
                      keeps every engine function in scope and the guarded
                      module.exports line stays inert.

Also asserts the P0 Sorgfaltspflicht: `bonus(matched, pct)` is a standalone,
exported engine function, not something inlined in score().
"""
import json
import os
import shutil
import subprocess
import sys
import unittest

# Allow both `python -m unittest discover -s tests` and `-m unittest tests.test_x`.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from engine_harness import EngineTestCase, ROOT, NODE, node_available  # noqa: E402

MIRROR = os.path.join(ROOT, "engine", "engine.js")


class TestHarnessNodePath(EngineTestCase):
    """One Node process, JSON-Lines batch, exercising the exported primitives."""

    def test_exports_non_empty_and_include_bonus(self):
        ex = self.engine.exports()
        self.assertTrue(ex, "engine exports must not be empty")
        self.assertIn("bonus", ex, "bonus must be an exported engine function")
        for name in ("score", "lineup", "grade", "tokens", "loss", "eligible"):
            self.assertIn(name, ex)

    def test_bonus_is_floor_of_sum_times_pct(self):
        # Oracle bands from the plan: floor(sum * pct).
        self.assertEqual(self.engine.call("bonus", [{"score": 325}, {"score": 325}], 0.02), 13)
        self.assertEqual(self.engine.call("bonus", [{"score": 700}], 0.02), 14)
        self.assertEqual(self.engine.call("bonus", [{"score": 420}, {"score": 30}], 0.30), 135)
        self.assertEqual(self.engine.call("bonus", [{"score": 100}], 0), 0)

    def test_tokens_cumulative(self):
        totw = {"thresholds": {"D": 10, "C": 125000, "B": 175000, "A": 300000, "S": 550000},
                "rewards": {"D": 5, "C": 15, "B": 30, "A": 50, "S": 75}}
        malaga = {"thresholds": {"D": 10, "C": 300, "B": 400, "A": 700, "S": 900},
                  "rewards": {"D": 0, "C": 0, "B": 5, "A": 8, "S": 15}}
        self.assertEqual(self.engine.call("tokens", totw, "S"), 175)
        self.assertEqual(self.engine.call("tokens", malaga, "S"), 28)
        self.assertEqual(self.engine.call("tokens", malaga, "B"), 5)

    def test_score_shape(self):
        r = self.engine.call("score", [{"score": 100}], {"countTopTags": 10})
        self.assertEqual(r, {"base": 100, "bonus": 0, "total": 100, "tags": []})


@unittest.skipUnless(node_available(), "node not found on PATH")
class TestHarnessBrowserPath(unittest.TestCase):
    """Evaluate the mirror with module=undefined (browser) -- exports line inert."""

    def test_browser_simulation(self):
        # The mirror path is passed via argv (process.argv[1]); embedding a
        # Windows path into the -e source would mangle its backslashes.
        script = (
            "const fs=require('fs');"
            "const src=fs.readFileSync(process.argv[1],'utf8');"
            "const fn=new Function('module',src+'\\nreturn {score,bonus,tokens,TAG};');"
            "const e=fn(undefined);"
            "process.stdout.write(JSON.stringify({"
            "score:typeof e.score,bonus:typeof e.bonus,"
            "tags:Object.keys(e.TAG).length,"
            "smoke:e.bonus([{score:325},{score:325}],0.02)"
            "}));"
        )
        out = subprocess.run([NODE, "-e", script, MIRROR],
                             capture_output=True, text=True, cwd=ROOT, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        d = json.loads(out.stdout)
        self.assertEqual(d["score"], "function", "browser path must still expose score")
        self.assertEqual(d["bonus"], "function", "browser path must still expose bonus")
        self.assertEqual(d["tags"], 21, "TAG must carry all 21 bonus tags")
        self.assertEqual(d["smoke"], 13)


if __name__ == "__main__":
    unittest.main(verbosity=2)
