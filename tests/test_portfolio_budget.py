#!/usr/bin/env python3
"""P3 rework -- the interactive first run is ONE budgeted global portfolio search.

Before the rework the app computed 127 independent `planSet` results on every
render (~288 s on the frozen 127x3000 dataset). P3 replaced that with a single
`portfolioPlan` call carrying a SHARED total budget:

  * `totalBudgetMs` caps the WHOLE call (seed + global B&B + refine + reporting),
    so the call returns within its budget and reports `node_limit` ("best found")
    instead of running unbounded;
  * `detail:false` skips the per-set breakdown, which the UI loads lazily via
    `portfolioDetail`;
  * the UI schedules the search with `setTimeout` (non-blocking) and computes the
    per-set list on demand in small batches.

These tests pin the ENGINE behaviour (budget respected, detail lazy, still valid)
and the UI WIRING (the non-blocking entry points exist and are used). All cards
are synthetic (R5).
"""

import os
import random
import sys
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
from engine_harness import EngineTestCase, node_available  # noqa: E402


def setdef(sid, slots, club="AC", thresholds=None):
    return {
        "id": sid, "name": sid, "slots": slots,
        "eligibility": {"type": "club", "value": club},
        "thresholds": thresholds or {"D": 10, "C": 300, "B": 600, "A": 900, "S": 1200},
        "rewards": {"D": 0, "C": 5, "B": 10, "A": 20, "S": 40},
    }


def card(iid, score, *, club="AC", nation="Spain", position="CM",
         collected=False, buy=None, resale=None):
    p = {"id": iid, "itemId": iid, "playerKey": iid, "name": iid, "score": score,
         "club": club, "nation": nation, "position": position, "league": "L",
         "rarity": "Gold", "special": "", "collected": collected}
    if buy is not None:
        p["buyPrice"] = buy
        p["resalePrice"] = resale if resale is not None else buy
    return p


def world(seed, sets=6, cands_per_set=40, owned_per_set=3):
    """A multi-set world with a shared card eligible for every set."""
    rng = random.Random(seed)
    players = []
    galleries = []
    for s in range(sets):
        sid = "g%d" % s
        galleries.append(setdef(sid, slots=5))
        for i in range(owned_per_set):
            players.append(card("%s_o%d" % (sid, i), rng.randint(60, 200),
                                collected=True, nation=rng.choice(["Spain", "France"])))
        for i in range(cands_per_set):
            players.append(card("%s_c%02d" % (sid, i), rng.randint(40, 600),
                                nation=rng.choice(["Spain", "France", "Italy"]),
                                position=rng.choice(["CM", "ST", "GK", "CB"]),
                                buy=rng.randint(50, 900), resale=rng.randint(20, 500)))
    # One card eligible for ALL sets (same club) -> genuinely shared.
    players.append(card("shared", 500, club="AC", buy=300, resale=100))
    return galleries, players


@unittest.skipUnless(node_available(), "node not found on PATH")
class TestPortfolioSharedBudget(EngineTestCase):
    """`totalBudgetMs` must bound the WHOLE call and still return a valid plan."""

    def test_budget_is_respected(self):
        galleries, players = world(1)
        for budget in (400, 800, 1500):
            t0 = time.perf_counter()
            p = self.engine.call("portfolioPlan", galleries, players,
                                 {"objective": "eff", "taxRate": 0.05, "coins": 100000,
                                  "reserve": 0, "maxBundle": 4,
                                  "totalBudgetMs": budget, "detail": False})
            dt_ms = (time.perf_counter() - t0) * 1000
            # Generous CI bound: the call must not run away (a missing bound would
            # take seconds-to-minutes here); allow ~6x the budget for scheduling.
            self.assertLess(dt_ms, budget * 6 + 1500,
                            "budget=%d ms but call took %.0f ms" % (budget, dt_ms))
            self.assertIn(p["optimality"], ("proved", "node_limit"))
            self.assertIsInstance(p["chosen"], list)
            self.assertTrue(p["feasible"], "a best-found plan must still be feasible")

    def test_larger_budget_is_not_worse(self):
        """A bigger shared budget must not return a WORSE objective value."""
        galleries, players = world(2)
        small = self.engine.call("portfolioPlan", galleries, players,
                                 {"objective": "eff", "taxRate": 0.05, "coins": 100000,
                                  "reserve": 0, "maxBundle": 4,
                                  "totalBudgetMs": 300, "detail": False})
        big = self.engine.call("portfolioPlan", galleries, players,
                               {"objective": "eff", "taxRate": 0.05, "coins": 100000,
                                "reserve": 0, "maxBundle": 4,
                                "totalBudgetMs": 4000, "detail": False})
        self.assertGreaterEqual(big["value"], small["value"] - 1e-6,
                                "more budget produced a worse plan: %r < %r"
                                % (big["value"], small["value"]))

    def test_tiny_budget_still_returns_a_valid_plan(self):
        """Even a 1 ms budget must return a usable (feasible) plan, not crash."""
        galleries, players = world(3)
        p = self.engine.call("portfolioPlan", galleries, players,
                             {"objective": "eff", "taxRate": 0.05, "coins": 100000,
                              "reserve": 0, "maxBundle": 4,
                              "totalBudgetMs": 1, "detail": False})
        self.assertTrue(p["feasible"])
        self.assertIsInstance(p["chosen"], list)
        self.assertEqual(p["optimality"], "node_limit")


@unittest.skipUnless(node_available(), "node not found on PATH")
class TestCooperativeSearch(EngineTestCase):
    """`portfolioSearch` is a step machine: it pauses at its budget and RESUMES.

    This is what lets the UI keep the main thread free -- the search is advanced
    in small slices, an intermediate "best found" plan is available early, and
    "Improve further" extends the SAME search (the B&B stack, the incumbent and
    the memo survive) rather than recomputing it.
    """

    def _opts(self, **extra):
        o = {"objective": "eff", "taxRate": 0.05, "coins": 100000, "reserve": 0,
             "maxBundle": 4, "detail": False, "stepBudgetMs": 25, "totalBudgetMs": 300}
        o.update(extra)
        return o

    def test_step_machine_advances_in_small_slices(self):
        galleries, players = world(11, sets=5, cands_per_set=60)
        r = self.engine.call("portfolioSearch", galleries, players, self._opts())
        self.assertGreater(r["steps"], 0, "the search must be advanced in steps")
        # The longest single slice must be small -- that is the whole point. The
        # innermost routines (`lineup`/`evalSet`/the lazy base) yield too, so a
        # slice is bounded by ~one swap batch, not by a whole set evaluation.
        self.assertLess(r["maxStepMs"], 250,
                        "a single step blocked for %s ms" % r["maxStepMs"])
        # A first plan (even "buy nothing") must appear quickly.
        self.assertIsNotNone(r["firstPlanMs"], "no intermediate plan was published")
        self.assertLess(r["firstPlanMs"], 2000)
        # It stops at its budget, keeping a valid best-found intermediate.
        self.assertTrue(r["paused"] or r["done"])
        self.assertIsNotNone(r["bestValue"])
        self.assertIsInstance(r["bestCards"], int)

    def test_resume_never_returns_a_worse_plan(self):
        """Extending the SAME search must not lose the incumbent."""
        galleries, players = world(12, sets=5, cands_per_set=60)
        short = self.engine.call("portfolioSearch", galleries, players, self._opts(totalBudgetMs=200))
        long_ = self.engine.call("portfolioSearch", galleries, players,
                                 self._opts(totalBudgetMs=200, resumeMs=4000, maxPauses=1))
        self.assertGreater(long_["pauses"], 0, "the long run never resumed")
        self.assertGreaterEqual(long_["bestValue"], short["bestValue"] - 1e-6,
                                "resuming returned a worse plan")

    def test_resume_does_not_restart_the_search(self):
        """Resuming must keep going, not start over (steps keep accumulating)."""
        galleries, players = world(13, sets=5, cands_per_set=60)
        r = self.engine.call("portfolioSearch", galleries, players,
                             self._opts(totalBudgetMs=150, resumeMs=3000, maxPauses=1))
        self.assertGreater(r["pauses"], 0)
        self.assertGreater(r["steps"], 3, "resumed search made almost no progress")


@unittest.skipUnless(node_available(), "node not found on PATH")
class TestLazyDetail(EngineTestCase):
    """`detail:false` must skip the breakdown; `portfolioDetail` recomputes it."""

    def test_detail_false_returns_none(self):
        galleries, players = world(4)
        p = self.engine.call("portfolioPlan", galleries, players,
                             {"objective": "eff", "taxRate": 0.05, "coins": 100000,
                              "reserve": 0, "maxBundle": 4, "totalBudgetMs": 2000,
                              "detail": False})
        self.assertIsNone(p["detail"], "detail:false must not compute the breakdown")

    def test_detail_default_is_computed(self):
        galleries, players = world(5)
        p = self.engine.call("portfolioPlan", galleries, players,
                             {"objective": "eff", "taxRate": 0.05, "coins": 100000,
                              "reserve": 0, "maxBundle": 4, "totalBudgetMs": 2000})
        self.assertIsInstance(p["detail"], list)
        self.assertEqual(len(p["detail"]), len(galleries))

    def test_lazy_detail_matches_inline_detail(self):
        """`portfolioDetail(chosen)` must equal the inline `detail` rows."""
        galleries, players = world(6)
        opts = {"objective": "eff", "taxRate": 0.05, "coins": 100000,
                "reserve": 0, "maxBundle": 4, "totalBudgetMs": 2500}
        p = self.engine.call("portfolioPlan", galleries, players, opts)
        lazy = self.engine.call("portfolioDetail", galleries, players,
                                {"objective": "eff", "taxRate": 0.05, "coins": 100000,
                                 "reserve": 0, "maxBundle": 4}, p["chosen"])
        self.assertEqual(len(lazy), len(p["detail"]))
        for a, b in zip(lazy, p["detail"]):
            self.assertEqual(a["set"], b["set"])
            self.assertAlmostEqual(a["dTokens"], b["dTokens"], places=6)
            self.assertAlmostEqual(a["dScore"], b["dScore"], places=6)
            self.assertEqual(a["newGrade"], b["newGrade"])


class TestOptimizerUiIsNonBlocking(unittest.TestCase):
    """Source-level wiring: the optimizer must be scheduled, not run inline."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(_ROOT, "index.html"), encoding="utf-8") as f:
            cls.html = f.read()

    def test_scheduler_exists_and_is_used(self):
        self.assertIn("function scheduleOptimize(", self.html)
        self.assertIn("function startSearch(", self.html)
        self.assertIn("function pumpSearch(", self.html)
        # the UI drives the COOPERATIVE engine search, in slices
        self.assertIn("portfolioSearch(state.galleries,state.players", self.html)
        self.assertIn("_search.step(SEARCH_SLICE_MS)", self.html)
        # each slice is scheduled, so the browser can paint between them
        self.assertIn("setTimeout(()=>pumpSearch(token),0)", self.html)

    def test_render_does_not_run_the_sweep_inline(self):
        """`render()` must NOT call the expensive per-set sweep synchronously."""
        self.assertIn("scheduleOptimize(false)", self.html,
                      "render() must schedule the optimizer instead of running it")
        # the old synchronous sweep line must be gone from render()
        self.assertNotIn("last=allOpps();dashOpps.innerHTML", self.html)

    def test_shared_budget_is_used_by_the_ui(self):
        self.assertIn("totalBudgetMs", self.html)
        self.assertIn("OPT_INTERACTIVE_MS", self.html)
        self.assertIn("OPT_IMPROVE_MS", self.html)

    def test_improve_resumes_instead_of_recomputing(self):
        """"Improve further" must EXTEND the same search, not start a new one.

        The step machine keeps the B&B stack, the incumbent and the memo, so
        resuming continues where the search stopped; a fresh `startSearch` would
        throw that away.
        """
        self.assertIn("function runImprove(", self.html)
        self.assertIn("improve.onclick=runImprove", self.html)
        self.assertIn("_search.extend(OPT_IMPROVE_MS)", self.html)
        self.assertIn("extend(ms)", self.html)
        self.assertNotIn("OPT_BACKGROUND_MS", self.html)

    def test_player_table_is_virtualised(self):
        """The collection table must render only a window, not every row."""
        self.assertIn("PLAYER_ROW_H", self.html)
        self.assertIn("function paintPlayerWindow(", self.html)
        self.assertIn("function onPlayersScroll(", self.html)
        self.assertIn("playersScroll", self.html)
        # spacer rows keep the scroll height while only the window is in the DOM
        self.assertIn("class=\"spacer\"", self.html)

    def test_per_set_is_on_demand_and_chunked(self):
        self.assertIn("function computePerSet(", self.html)
        self.assertIn("runPerSet.onclick=computePerSet", self.html)
        # the per-set loop yields between batches
        self.assertIn("setTimeout(step,0)", self.html)

    def test_inner_routines_are_interruptible(self):
        """`lineup`/`evalSet`/the lazy base must yield, not just the outer search.

        Otherwise the atomic unit is a whole set evaluation (~100 ms) and the tick
        target cannot be met. Both keep their synchronous signatures as draining
        wrappers, so every other caller is unchanged.
        """
        self.assertIn("function* _lineupGen(", self.html)
        self.assertIn("function* _evalSetGen(", self.html)
        self.assertIn("function* _pfBaseGen(", self.html)
        self.assertIn("const l = yield* _lineupGen(", self.html)
        self.assertIn("yield null; // interruptible point", self.html)
        # the synchronous wrappers drain the generators
        self.assertIn("const g = _lineupGen(pool, n);", self.html)
        self.assertIn("const gen = _evalSetGen(g, pool, idSet);", self.html)
        # the lazy base must go through the interruptible path
        self.assertIn("baseGen: w.baseGen", self.html)

    def test_lazy_detail_is_chunked(self):
        self.assertIn("function lazyDetail(", self.html)
        self.assertIn("portfolioDetail(", self.html)

    def test_objective_change_replans_with_the_interactive_budget(self):
        """Changing the objective must trigger a re-plan (not a stale panel)."""
        self.assertIn("scheduleOptimize(true)", self.html)


if __name__ == "__main__":
    unittest.main()
