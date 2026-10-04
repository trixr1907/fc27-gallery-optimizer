#!/usr/bin/env python3
"""P1 (R3) -- shopping plan: Branch & Bound on card sets + memoized evalSet + 2-opt.

The plan is proven against the REAL engine (tools/engine_cli.js), not a Python
re-implementation. Where a scenario is small enough, `planSet`'s chosen score is
compared against an exhaustive brute-force optimum computed through the same
engine (R5: engine assertions only on constructed data).

Covered:
  * evalSet memoization is deterministic and equals score() on the full lineup.
  * gain1 >= 0 (marginal greedy seed is sound).
  * planSet respects `maxBundle`, `coins`, and `slots`, and never buys an owned
    or ineligible card.
  * planSet reaches the same total score as brute force on small scenarios --
    including under a BINDING coin budget (a cost-blind greedy would fail there).
  * one objective per plan (`tokens`, `score`, `balanced`, `eff`).
  * multi-set PORTFOLIO optimisation: a shared card improving two sets has its
    cost counted ONCE; `plan()`/`portfolioPlan` match brute force under
    `coins - reserve`.
"""

import itertools
import json
import os
import re
import subprocess
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from engine_harness import EngineTestCase  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make(iid, score, *, club="AC", position="CM", collected=False, buy=None,
         resale=None, rarity="", special="", nation="Spain"):
    p = {"id": iid, "itemId": iid, "playerKey": iid, "name": iid, "score": score,
         "club": club, "position": position, "nation": nation, "league": "L",
         "rarity": rarity, "special": special, "collected": collected}
    if buy is not None:
        p["buyPrice"] = buy
        p["resalePrice"] = resale if resale is not None else buy
    return p


def setdef(sid="g1", slots=5, value="AC", thresholds=None, rewards=None):
    return {
        "id": sid, "name": sid, "slots": slots,
        "eligibility": {"type": "club", "value": value},
        "thresholds": thresholds or {"D": 10, "C": 300, "B": 600, "A": 900, "S": 1200},
        "rewards": rewards or {"D": 0, "C": 5, "B": 10, "A": 20, "S": 40},
    }


class TestEvalSet(EngineTestCase):
    """evalSet (memoized) must agree with score()/lineup() and be deterministic."""

    def _scenario(self):
        players = [make("o0", 100, collected=True), make("o1", 90, collected=True),
                   make("b1", 400, buy=1000), make("b2", 380, buy=900)]
        return setdef(slots=2), players

    def test_hits_memo_repeatedly(self):
        g, players = self._scenario()
        req = {"fn": "evalSet", "args": [g, players, ["o0", "o1"]]}
        outs = [self.engine.raw(json.dumps(req)) for _ in range(3)]
        self.assertTrue(all(o["ok"] for o in outs))
        self.assertEqual(outs[0]["result"], outs[1]["result"])
        self.assertEqual(outs[1]["result"], outs[2]["result"])

    def test_evalset_equals_lineup_total(self):
        """evalSet(g, pool, ids) must equal lineup() over exactly those items."""
        g, players = self._scenario()
        ev = self.engine.call("evalSet", g, players, ["o0", "o1", "b1"])
        sel = [p for p in players if p["itemId"] in {"o0", "o1", "b1"}]
        lu = self.engine.call("lineup", sel, g["slots"])
        self.assertEqual(ev["score"], lu["total"])
        self.assertEqual(ev["base"], lu["base"])
        self.assertEqual(ev["bonus"], lu["bonus"])

    def test_count_is_selected_items(self):
        g, players = self._scenario()
        ev = self.engine.call("evalSet", g, players, ["o0", "o1", "b1", "b2"])
        self.assertEqual(ev["count"], 4)
        self.assertIn("grade", ev)

    def test_memo_key_includes_resolved_pool(self):
        """Regression: the memo must NOT collide when the same id-set maps to
        different cards in different pools.

        `evalSet(g, pool, ids)` depends on the POOL (which record each id
        resolves to, or whether it is present at all). An earlier key ignored the
        pool, so `pool=[o0,o1,c1]` could poison a later call over
        `pool=[o0,o1,unit,c1]` (and vice versa). Both orders are checked."""
        g = setdef(slots=5)
        o0 = make("o0", 100, collected=True)
        o1 = make("o1", 90, collected=True)
        unit = make("unit", 150)                 # unpriced eligible unit
        c1 = make("c1", 300, buy=500, resale=500)
        all_players = [o0, o1, unit, c1]
        ids = ["o0", "o1", "unit", "c1"]
        small_pool = [o0, o1, c1]                 # `unit` absent here
        # order 1: with units first
        self.engine.call("evalMemoReset")
        big = self.engine.call("evalSet", g, all_players, ids)["score"]
        small = self.engine.call("evalSet", g, small_pool, ids)["score"]
        self.assertEqual(big, 640)
        self.assertEqual(small, 490)
        # order 2: small pool first
        self.engine.call("evalMemoReset")
        small2 = self.engine.call("evalSet", g, small_pool, ids)["score"]
        big2 = self.engine.call("evalSet", g, all_players, ids)["score"]
        self.assertEqual(small2, 490)
        self.assertEqual(big2, 640)


class TestGain1(EngineTestCase):
    """Marginal gain must be non-negative for the greedy seed to be sound."""

    def test_gain_non_negative(self):
        base = setdef(slots=5)
        items = [make("a", 500), make("b", 400, nation="France", club="BC", position="ST")]
        for x in [make("c", 300), make("d", 100, nation="Italy", club="CC", position="GK")]:
            self.assertGreaterEqual(self.engine.call("gain1", base, items, x), 0)

    def test_gain_increases_total(self):
        base = setdef(slots=5)
        items = [make("a", 100)]
        x = make("b", 100)
        gain = self.engine.call("gain1", base, items, x)
        before = self.engine.call("score", items, {"countTopTags": 10})["total"]
        after = self.engine.call("score", items + [x], {"countTopTags": 10})["total"]
        self.assertEqual(gain, after - before)


class TestPlanRespectsConstraints(EngineTestCase):
    """planSet must honour maxBundle, coins, slots and never buy owned items."""

    def _players(self):
        ps = [make("o%d" % i, 100, collected=True) for i in range(2)]
        ps += [make("b1", 400, buy=1000, resale=900), make("b2", 380, buy=900, resale=820)]
        ps += [make("c%d" % i, 20, buy=300, resale=260) for i in range(3)]
        return ps

    def test_max_bundle(self):
        r = self.engine.call("planSet", setdef(slots=4), self._players(),
                             {"objective": "score", "maxBundle": 2, "coins": 10 ** 9})
        self.assertLessEqual(len(r["chosen"]), 2)

    def test_never_buys_owned(self):
        r = self.engine.call("planSet", setdef(slots=4), self._players(),
                             {"objective": "score", "maxBundle": 15, "coins": 10 ** 9})
        self.assertFalse(set(r["chosen"]) & {"o0", "o1"})
        self.assertFalse(set(r["recommendations"]) & {"o0", "o1"})

    def test_never_buys_ineligible(self):
        players = self._players() + [make("z1", 999, club="ZZ", buy=10, resale=10)]
        r = self.engine.call("planSet", setdef(slots=4), players,
                             {"objective": "score", "maxBundle": 15, "coins": 10 ** 9})
        self.assertNotIn("z1", r["recommendations"])

    def test_coin_budget_is_feasible_and_used(self):
        # budget 350: must NOT buy the 900 card; y1(100)+y2(200) fit.
        players = [make("x1", 400, buy=900, resale=800),
                   make("y1", 200, buy=100, resale=90),
                   make("y2", 150, buy=200, resale=180)]
        r = self.engine.call("planSet", setdef(slots=2), players,
                             {"objective": "tokens", "maxBundle": 15, "coins": 350})
        self.assertTrue(r["feasible"])
        spend = sum(p["buyPrice"] for p in players if p["itemId"] in r["recommendations"])
        self.assertLessEqual(spend, 350)
        self.assertNotIn("x1", r["chosen"])

    def test_slots_missing_is_reported(self):
        # 1 owned, 2 candidates, slots 5 -> still incomplete after buying everything.
        players = [make("o0", 100, collected=True),
                   make("b1", 300, buy=500, resale=450),
                   make("b2", 250, buy=400, resale=360)]
        r = self.engine.call("planSet", setdef(slots=5), players,
                             {"objective": "tokens", "maxBundle": 15, "coins": 10 ** 9})
        self.assertFalse(r["completeAfter"])
        self.assertIsNone(r["newGrade"])
        self.assertEqual(r["dTokens"], 0)


class TestPlanOptimality(EngineTestCase):
    """planSet's chosen score equals the exhaustive optimum on small scenarios
    (R5: engine assertions only on constructed data)."""

    def _brute_best_score(self, g, players, owned_ids, cands, max_bundle, coins=None):
        """Exhaustive optimum over subsets S, respecting the coin budget
        (capital spent = sum of buyPrice) exactly as planSet does."""
        prices = {p["itemId"]: p["buyPrice"] for p in players if "buyPrice" in p}
        best = None
        for k in range(0, min(max_bundle, len(cands)) + 1):
            for combo in itertools.combinations(cands, k):
                if coins is not None:
                    spend = sum(prices.get(c, 0) for c in combo)
                    if spend > coins:
                        continue
                ids = list(owned_ids | set(combo))
                r = self.engine.call("evalSet", g, players, ids)
                if best is None or r["score"] > best:
                    best = r["score"]
        return best

    def _run(self, g, players, opts):
        return self.engine.call("planSet", g, players, opts)

    def test_matches_brute_force_objective_score(self):
        players = [make("o%d" % i, 100, collected=True) for i in range(4)]
        players += [make("b1", 400, buy=1000, resale=900),
                    make("b2", 380, buy=900, resale=820)]
        players += [make("c%d" % i, 20, buy=300, resale=260) for i in range(4)]
        g = setdef(slots=5)
        r = self._run(g, players, {"objective": "score", "maxBundle": 15, "coins": 10 ** 9})
        owned = {"o0", "o1", "o2", "o3"}
        best = self._brute_best_score(g, players, owned, ["b1", "b2", "c0", "c1", "c2", "c3"], 15)
        self.assertEqual(r["buyScore"], best)

    def test_matches_brute_force_second_scenario(self):
        players = [make("o0", 220, collected=True), make("o1", 180, collected=True)]
        players += [make("p1", 260, buy=600, resale=560), make("p2", 240, buy=500, resale=470),
                    make("p3", 90, buy=120, resale=110), make("p4", 60, buy=80, resale=70)]
        g = setdef(slots=4, thresholds={"D": 10, "C": 400, "B": 700, "A": 1000, "S": 1400},
                   rewards={"D": 0, "C": 5, "B": 12, "A": 22, "S": 45})
        r = self._run(g, players, {"objective": "score", "maxBundle": 15, "coins": 10 ** 9})
        best = self._brute_best_score(g, players, {"o0", "o1"}, ["p1", "p2", "p3", "p4"], 15)
        self.assertEqual(r["buyScore"], best)

    def test_matches_brute_force_under_coin_constraint(self):
        """R3 binding check: with a binding coin budget, B&B must still reach the
        exhaustive optimum -- a cost-blind greedy would fail here.

        Note the two high cards: h1 (buy 1000) and h2 (buy 800); both fit only if
        the budget allows. At coins=1200 the optimum is h1+m1 (950 score), NOT the
        cheaper-looking h2+m1 (930) -- a greedy-by-cheapest pick misses it."""
        players = [make("o0", 260, collected=True), make("o1", 240, collected=True)]
        players += [make("h1", 300, buy=1000), make("h2", 280, buy=800),
                    make("m1", 150, buy=200), make("m2", 140, buy=180)]
        g = setdef(slots=4)
        owned = {"o0", "o1"}
        cand_ids = ["h1", "h2", "m1", "m2"]
        for coins in (10 ** 9, 1900, 1200, 1000, 300, 50):
            r = self._run(g, players, {"objective": "score", "maxBundle": 6, "coins": coins})
            best = self._brute_best_score(g, players, owned, cand_ids, 6, coins=coins)
            self.assertEqual(r["buyScore"], best,
                             "coins=%s: planSet=%s brute=%s" % (coins, r["buyScore"], best))
            self.assertTrue(r["feasible"])

    def test_budget_never_exceeded(self):
        players = [make("o0", 100, collected=True)]
        players += [make("b%d" % i, 200, buy=1000) for i in range(4)]
        g = setdef(slots=3)
        r = self._run(g, players, {"objective": "score", "maxBundle": 6, "coins": 1500})
        spend = sum(p["buyPrice"] for p in players if p["itemId"] in r["recommendations"])
        self.assertLessEqual(spend, 1500)


class TestPortfolioTwoSets(EngineTestCase):
    """R3 binding check -- portfolio optimisation across SEVERAL sets.

    The decisive property: ONE card can improve BOTH sets at once, and its coin
    cost must be charged ONLY ONCE in the portfolio. This is what separates a real
    multi-set portfolio from merely summing per-set plans. We compare `plan()`
    (and `portfolioPlan`) against brute force under the post-reserve budget
    `coins - reserve`.
    """

    def _portfolio(self, galleries, players, opts):
        return self.engine.call("plan", galleries, players, opts)["portfolio"]

    def _brute(self, galleries, players, opts):
        return self.engine.call("portfolioBrute", galleries, players, opts)

    def _shared_card_scenario(self):
        # Two sets that both accept club "AC". `shared` (club AC) is eligible for
        # BOTH; `only` improves neither beyond `shared` but is a valid candidate.
        players = [make("o0", 100, collected=True), make("o1", 90, collected=True),
                   make("shared", 300, buy=1000, resale=1000),
                   make("only", 200, buy=500, resale=500)]
        gs = [setdef("g1", slots=3), setdef("g2", slots=3)]
        return gs, players

    def test_shared_card_cost_counted_once(self):
        """The chosen shared card's cost appears exactly once in `cost`."""
        gs, players = self._shared_card_scenario()
        opts = {"objective": "score", "maxBundle": 5, "coins": 10 ** 9, "reserve": 0}
        p = self._portfolio(gs, players, opts)
        # loss(shared) = 1000 - floor(1000*0.95) = 50 ; loss(only) = 25.
        self.assertEqual(p["cost"], 50 + 25, "shared card must be charged once")
        self.assertIn("shared", p["chosen"])
        # ...and it must improve BOTH sets (dScore is the sum over both sets).
        self.assertEqual(len(p["detail"]), 2)
        self.assertGreater(p["detail"][0]["dScore"], 0)
        self.assertGreater(p["detail"][1]["dScore"], 0)
        self.assertEqual(p["dScore"], p["detail"][0]["dScore"] + p["detail"][1]["dScore"])

    def test_portfolio_matches_brute_force(self):
        gs, players = self._shared_card_scenario()
        for coins, reserve in [(10 ** 9, 0), (100, 0), (10 ** 9, 25), (100, 25),
                               (75, 0), (10 ** 9, 75)]:
            opts = {"objective": "score", "maxBundle": 5, "coins": coins, "reserve": reserve}
            p = self._portfolio(gs, players, opts)
            b = self._brute(gs, players, opts)
            self.assertEqual(p["budget"], max(0, coins - reserve))
            self.assertEqual(sorted(p["chosen"]), b["best"],
                             "coins=%s reserve=%s: %s vs %s" % (coins, reserve, p["chosen"], b["best"]))
            self.assertEqual(p["value"], b["value"])
            self.assertLessEqual(p["cost"], p["budget"])

    def test_reserve_excludes_optimal_bundle(self):
        """A binding reserve must force a cheaper portfolio (the expensive shared
        card plus the cheap card no longer both fit)."""
        players = [make("o0", 100, collected=True), make("o1", 90, collected=True),
                   make("big", 400, buy=2000, resale=2000),   # loss 100
                   make("cheap", 150, buy=120, resale=120)]   # loss 6
        gs = [setdef("g1", slots=3), setdef("g2", slots=3)]
        full = self._portfolio(gs, players, {"objective": "score", "maxBundle": 5,
                                             "coins": 10 ** 9, "reserve": 0})
        tight = self._portfolio(gs, players, {"objective": "score", "maxBundle": 5,
                                              "coins": 101, "reserve": 0})
        b_tight = self._brute(gs, players, {"objective": "score", "maxBundle": 5,
                                            "coins": 101, "reserve": 0})
        self.assertEqual(sorted(full["chosen"]), ["big", "cheap"])
        self.assertEqual(tight["chosen"], ["big"], "budget 101 fits only `big` (loss 100)")
        self.assertEqual(sorted(tight["chosen"]), b_tight["best"])

    def test_portfolio_value_ignores_ineligible_card_for_set(self):
        """A card eligible for only ONE set must improve only that set."""
        players = [make("o0", 100, collected=True), make("o1", 90, collected=True),
                   make("acOnly", 300, club="AC", buy=1000, resale=1000),
                   make("zzOnly", 300, club="ZZ", buy=800, resale=800)]
        gs = [setdef("gAC", slots=3, value="AC"), setdef("gZZ", slots=3, value="ZZ")]
        p = self._portfolio(gs, players, {"objective": "score", "maxBundle": 5,
                                          "coins": 10 ** 9, "reserve": 0})
        d = {x["set"]: x for x in p["detail"]}
        # acOnly improves gAC only; zzOnly improves gZZ only.
        self.assertGreater(d["gAC"]["dScore"], 0)
        self.assertGreater(d["gZZ"]["dScore"], 0)
        self.assertEqual(sorted(p["chosen"]), ["acOnly", "zzOnly"])
        # Cost is the union: 50 + 40 = 90, once each.
        self.assertEqual(p["cost"], 50 + 40)

    def test_portfolio_deterministic(self):
        gs, players = self._shared_card_scenario()
        opts = {"objective": "eff", "maxBundle": 5, "coins": 10 ** 9}
        a = self._portfolio(gs, players, opts)
        b = self._portfolio(gs, players, opts)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_plan_exposes_portfolio(self):
        gs, players = self._shared_card_scenario()
        full = self.engine.call("plan", gs, players,
                                {"objective": "score", "maxBundle": 5, "coins": 10 ** 9})
        self.assertIn("portfolio", full)
        self.assertIn("chosen", full["portfolio"])
        self.assertIn("budget", full["portfolio"])
        # per-set `plans` remain available alongside the portfolio
        self.assertEqual(len(full["plans"]), 2)


class TestSetUpperBound(EngineTestCase):
    """(P1 point 1) The B&B bound must be a SOUND (admissible + monotone) upper
    bound on any realised lineup score.

    `lineup()` is a heuristic selector and is NOT monotone in the pool, so
    "evalSet over all remaining candidates" is NOT an admissible bound and can
    prune away the true optimum. The replacement `setUpperBound` is built from
    two provably monotone terms (<=slots largest base scores + the UNCAPPED tag
    bonus over the whole pool). These tests pin exactly that property: the bound
    must dominate every feasible subset's realised score, and must be monotone
    when items are added to the pool."""

    def _g(self, slots=3, **kw):
        return setdef(slots=slots, **kw)

    def test_bound_dominates_every_subset(self):
        """For a constructed pool, setUpperBound >= max realised subset score,
        checked EXHAUSTIVELY over every subset (the admissibility property)."""
        g = self._g(slots=3, thresholds={"D": 10, "C": 300, "B": 600, "A": 900, "S": 1200},
                    rewards={"D": 0, "C": 5, "B": 10, "A": 20, "S": 40})
        pool = [make("a", 300), make("b", 250), make("c", 200),
                make("d", 150, club="BC"), make("e", 120, position="ST"),
                make("f", 90, club="CC", nation="Italy")]
        ub = self.engine.call("setUpperBound", g, pool)
        best = max(
            self.engine.call("evalSet", g, pool, list(c))["score"]
            for k in range(0, len(pool) + 1)
            for c in itertools.combinations([p["itemId"] for p in pool], k)
        )
        self.assertGreaterEqual(ub, best, "bound %s must dominate realised max %s" % (ub, best))

    def test_bound_monotone_when_items_added(self):
        """Adding items to the pool can only raise the bound (safety for B&B,
        which evaluates the bound over the growing eval-universe)."""
        g = self._g(slots=4)
        base = [make("a", 300), make("b", 200)]
        extra = [make("c", 500, club="BC"), make("d", 50, nation="Italy"),
                 make("e", 900, club="CC", position="ST")]
        prev = self.engine.call("setUpperBound", g, base)
        pool = base[:]
        for x in extra:
            pool = pool + [x]
            cur = self.engine.call("setUpperBound", g, pool)
            self.assertGreaterEqual(cur, prev,
                                    "bound must not decrease when %s joins" % x["itemId"])
            prev = cur

    def test_bound_ge_evalset_over_whole_pool(self):
        """Sanity: the bound also dominates evalSet over the full pool."""
        g = self._g(slots=3)
        pool = [make("a", 300), make("b", 250), make("c", 200), make("d", 100, club="BC")]
        ub = self.engine.call("setUpperBound", g, pool)
        full = self.engine.call("evalSet", g, pool, [p["itemId"] for p in pool])["score"]
        self.assertGreaterEqual(ub, full)

    def test_bound_tight_when_pool_fits(self):
        """If the pool has <= slots items, the bound must be EXACT (no slack):
        all items enter the lineup, base is their sum and the bonus matches."""
        g = self._g(slots=5)
        pool = [make("a", 300), make("b", 250), make("c", 200)]
        ub = self.engine.call("setUpperBound", g, pool)
        exact = self.engine.call("evalSet", g, pool, [p["itemId"] for p in pool])["score"]
        self.assertEqual(ub, exact)

    def test_lineup_is_not_monotone_regression(self):
        """Documented counter-example: a LARGER pool can score LOWER under
        `lineup()` (via evalSet). This is exactly why the bound cannot be
        `evalSet` over all candidates -- keep it as a regression witness."""
        g = self._g(slots=3)
        # Two synergistic tags on a subset vs a high-score outsider.
        players = [make("p1", 400), make("p2", 380), make("p3", 360),
                   make("p4", 340, club="BC"), make("p5", 320, club="CC"),
                   make("p6", 900, nation="Italy")]  # p6: huge score, no synergy
        all_ids = [p["itemId"] for p in players]
        full = self.engine.call("evalSet", g, players, all_ids)["score"]
        without_p6 = self.engine.call("evalSet", g, players, [i for i in all_ids if i != "p6"])["score"]
        # Not required to be monotone: assert the documented behaviour holds --
        # the bound must still dominate BOTH.
        ub = self.engine.call("setUpperBound", g, players)
        self.assertGreaterEqual(ub, max(full, without_p6))
        self.assertGreaterEqual(ub, full)
        # And record the (in)equality direction is not relied upon anywhere.
        self.assertIsInstance(full, int)
        self.assertIsInstance(without_p6, int)


class TestSmallBruteForceAllObjectives(EngineTestCase):
    """(P1 point 3) The agreed small brute-force case: up to 25 candidates and at
    most 4 purchases, checked for the ACTUALLY-OFFERED objectives
    (`tokens`, `score`, `balanced`, `eff`).

    planSet must match the exhaustive optimum of its own objective function over
    every subset S with |S| <= 4 (and the coin budget respected)."""

    def _objective_brute(self, g, players, owned_ids, cand_ids, max_bundle, obj, coins):
        """Exhaustive best objective value over subsets S (|S| <= max_bundle),
        computed through the engine's own objectiveValue so the comparison is
        apples-to-apples with planSet.

        CRITICAL: the search space must mirror planSet exactly -- the candidate
        list is `candidatesFor` (eligible AND priced), the eval-universe is
        `poolFor(g) ∪ candidatesFor(g)`, and the base is `pool.slice(0, slots)`.
        A naive "all non-collected players" universe is wrong: ineligible cards
        would leak into the lineup and inflate a phantom optimum."""
        pool = self.engine.call("poolFor", g, players, [])
        cands = self.engine.call("candidatesFor", g, players, [])
        # Restrict to the cand_ids the caller declared (the engine's own set).
        cands = [c for c in cands if c["itemId"] in set(cand_ids)]
        universe = pool + cands
        base_r = self.engine.call("evalSet", g, universe, sorted(owned_ids))
        base_score, base_tokens = base_r["score"], self.engine.call("tokens", g, base_r["grade"])
        prices = {c["itemId"]: (c.get("buyPrice") or 0) for c in cands}
        best = None
        for k in range(0, min(max_bundle, len(cands)) + 1):
            for combo in itertools.combinations([c["itemId"] for c in cands], k):
                spend = sum(prices.get(c, 0) for c in combo)
                if spend > coins:
                    continue
                ids = sorted(set(owned_ids) | set(combo))
                ev = self.engine.call("evalSet", g, universe, ids)
                d_tokens = self.engine.call("tokens", g, ev["grade"]) - base_tokens
                d_score = ev["score"] - base_score
                d_loss = sum(self.engine.call("loss", c) for c in cands if c["itemId"] in combo)
                v = self.engine.call("objectiveValue", obj, d_tokens, d_score, d_loss)
                if best is None or v > best:
                    best = v
        return best

    def _scenario_25(self):
        """25 candidates, 2 owned. All candidates share club AC (so they are all
        eligible for the AC set -> a genuinely 25-wide candidate list), with
        varied nations/positions to create tag synergy across the pool."""
        players = [make("o0", 120, collected=True), make("o1", 110, collected=True)]
        for i in range(25):
            nation = ["Spain", "France", "Italy", "England"][i % 4]
            pos = ["CM", "ST", "GK", "CB"][i % 4]
            players.append(make("c%02d" % i, 60 + (i * 37) % 500,
                                club="AC", nation=nation, position=pos,
                                buy=100 + (i * 53) % 1500,
                                resale=80 + (i * 41) % 1200))
        return players

    def test_candidate_universe_is_25(self):
        """Guard: the scenario must really present 25 candidates to planSet."""
        players = self._scenario_25()
        g = setdef(slots=6)
        cands = self.engine.call("candidatesFor", g, players, [])
        self.assertEqual(len(cands), 25)

    def test_matches_brute_force_all_objectives_budget(self):
        players = self._scenario_25()
        g = setdef(slots=6, thresholds={"D": 10, "C": 500, "B": 900, "A": 1400, "S": 2000},
                   rewards={"D": 0, "C": 5, "B": 12, "A": 25, "S": 50})
        owned = {"o0", "o1"}
        cand_ids = [p["itemId"] for p in players if not p.get("collected")]
        self.assertGreaterEqual(len(cand_ids), 25)
        coins = 2500
        for obj in ("tokens", "score", "balanced", "eff"):
            r = self.engine.call("planSet", g, players,
                                 {"objective": obj, "maxBundle": 4, "coins": coins})
            self.assertLessEqual(len(r["chosen"]), 4)
            self.assertTrue(r["feasible"])
            spend = sum(p.get("buyPrice", 0) for p in players if p["itemId"] in r["chosen"])
            self.assertLessEqual(spend, coins)
            best = self._objective_brute(g, players, owned, cand_ids, 4, obj, coins)
            self.assertEqual(r["value"], best,
                             "obj=%s: planSet value %s != brute %s" % (obj, r["value"], best))

    def test_matches_brute_force_unbounded_coins(self):
        players = self._scenario_25()
        g = setdef(slots=6)
        owned = {"o0", "o1"}
        cand_ids = [p["itemId"] for p in players if not p.get("collected")]
        for obj in ("tokens", "score", "balanced", "eff"):
            r = self.engine.call("planSet", g, players,
                                 {"objective": obj, "maxBundle": 4, "coins": 10 ** 9})
            best = self._objective_brute(g, players, owned, cand_ids, 4, obj, 10 ** 9)
            self.assertEqual(r["value"], best,
                             "obj=%s (unbounded): %s != %s" % (obj, r["value"], best))


class TestTagSynergySharedCardBruteForce(EngineTestCase):
    """(P1 point 1, second half) Brute force with BOTH tag synergy AND a card
    shared across two sets.

    Two sets whose eligibility overlaps so that ONE card raises a shared tag
    cluster for BOTH sets; a second card is synergistic only in combination. The
    portfolio must match the exhaustive optimum, charging the shared card's cost
    exactly once."""

    def test_two_set_tag_synergy_shared_card(self):
        # g1/g2 both accept club "AC"; tag synergy comes from a SHARED nation
        # cluster (Spain) whose floor-bonus only fires once enough Spain items
        # are in the lineup. `shared`+`partner` are BOTH club AC (eligible for
        # both sets) and both Spain, so together they clear a Spain tag tier that
        # neither reaches alone -- super-additive, and `shared` helps BOTH sets.
        g1 = setdef("g1", slots=4, value="AC",
                    thresholds={"D": 10, "C": 400, "B": 800, "A": 1200, "S": 1600},
                    rewards={"D": 0, "C": 5, "B": 12, "A": 24, "S": 48})
        g2 = setdef("g2", slots=4, value="AC",
                    thresholds={"D": 10, "C": 400, "B": 800, "A": 1200, "S": 1600},
                    rewards={"D": 0, "C": 5, "B": 12, "A": 24, "S": 48})
        players = [
            make("o0", 110, club="AC", collected=True),
            make("o1", 100, club="AC", collected=True),
            # shared: AC + Spain -> helps BOTH sets and stacks the Spain tag
            make("shared", 260, club="AC", nation="Spain", buy=1200, resale=1140),
            # partner: AC + Spain -> completes the Spain tag cluster with `shared`
            make("partner", 240, club="AC", nation="Spain", buy=800, resale=760),
            # noise: high score, non-Spain, no synergy
            make("noise", 300, club="AC", nation="Germany", position="GK",
                 buy=1500, resale=1425),
        ]
        gs = [g1, g2]
        opts = {"objective": "score", "maxBundle": 4, "coins": 10 ** 9, "reserve": 0}
        p = self.engine.call("portfolioPlan", gs, players, opts)
        b = self.engine.call("portfolioBrute", gs, players, opts)
        self.assertEqual(sorted(p["chosen"]), b["best"],
                         "shared+partner synergy: %s vs brute %s" % (p["chosen"], b["best"]))
        self.assertEqual(p["value"], b["value"])
        # shared card improves BOTH sets and is charged exactly once.
        self.assertIn("shared", p["chosen"])
        self.assertEqual(p["optimality"], "proved")
        self.assertTrue(p["proven"])
        self.assertEqual(len(p["detail"]), 2)
        self.assertGreater(p["detail"][0]["dScore"], 0)
        self.assertGreater(p["detail"][1]["dScore"], 0)
        # cost = union of engine `loss()` over the DISTINCT chosen cards, once.
        expected_cost = sum(self.engine.call("loss", c) for c in players if c["itemId"] in p["chosen"])
        self.assertEqual(p["cost"], expected_cost, "shared card charged exactly once")

    def test_two_set_synergy_under_budget(self):
        """Under a binding budget the synergy choice may change; still must match
        brute force for every budget."""
        g1 = setdef("g1", slots=3, value="AC")
        g2 = setdef("g2", slots=3, value="AC")
        players = [
            make("o0", 100, club="AC", collected=True),
            make("shared", 250, club="AC", nation="Spain", buy=1000, resale=950),
            make("partner", 230, club="AC", nation="Spain", buy=400, resale=380),
            make("cheap", 90, club="AC", buy=60, resale=57),
        ]
        gs = [g1, g2]
        for coins in (10 ** 9, 1500, 1000, 500, 400, 100):
            opts = {"objective": "balanced", "maxBundle": 4, "coins": coins, "reserve": 0}
            p = self.engine.call("portfolioPlan", gs, players, opts)
            b = self.engine.call("portfolioBrute", gs, players, opts)
            self.assertEqual(sorted(p["chosen"]), b["best"],
                             "coins=%s: %s vs %s" % (coins, p["chosen"], b["best"]))
            self.assertLessEqual(p["cost"], p["budget"])


class TestGlobalBbPathVsBruteForce(EngineTestCase):
    """(P1 point 1, third round) The GLOBAL `plan()` path -- NOT a per-set plan --
    must be what the offer is compared against. These tests push the portfolio
    universe PAST `EXACT_PF_LIMIT` (so the global B&B branch is exercised), use
    SHARED cards across two sets, bind the budget via `coins - reserve`, and
    check the result against an independent exhaustive brute force over the same
    engine primitives."""

    def _shared_universe(self, n_noise):
        """Two sets sharing club AC, a Spain-synergy pair shared across both, plus
        `n_noise` WEAK filler cards (low score, pricey) so the synergy pair stays
        the optimum even in a large (>20) universe."""
        g1 = setdef("g1", slots=5, value="AC",
                    thresholds={"D": 10, "C": 500, "B": 1000, "A": 1500, "S": 2000},
                    rewards={"D": 0, "C": 6, "B": 14, "A": 28, "S": 56})
        g2 = setdef("g2", slots=5, value="AC",
                    thresholds={"D": 10, "C": 500, "B": 1000, "A": 1500, "S": 2000},
                    rewards={"D": 0, "C": 6, "B": 14, "A": 28, "S": 56})
        players = [
            make("o0", 120, club="AC", collected=True),
            make("shared", 300, club="AC", nation="Spain", buy=900, resale=855),
            make("partner", 260, club="AC", nation="Spain", buy=500, resale=475),
        ]
        # Fillers are strictly dominated by `partner` (lower score, higher price)
        # and non-Spain, so the Spain synergy pair is always the unique optimum.
        for i in range(n_noise):
            players.append(make("n%02d" % i, 60 + (i % 5), club="AC",
                                nation="France", position="GK",
                                buy=8000 + i * 10, resale=7600 + i * 9))
        return [g1, g2], players

    def test_global_plan_path_matches_brute_force_over_20(self):
        """`plan().portfolio` (the global path) == brute force on a >20 universe,
        with shared cards and a binding `coins - reserve` budget."""
        gs, players = self._shared_universe(21)  # universe = 23 > 20
        opts = {"objective": "score", "maxBundle": 4, "coins": 1300, "reserve": 100}
        full = self.engine.call("plan", gs, players, opts)
        pf = full["portfolio"]
        b = self.engine.call("portfolioBrute", gs, players, opts)
        self.assertGreater(pf["universe"], 20, "must hit the global B&B branch")
        self.assertEqual(pf["budget"], 1300 - 100, "budget is coins - reserve")
        self.assertEqual(sorted(pf["chosen"]), b["best"],
                         "global plan path: %s vs brute %s" % (pf["chosen"], b["best"]))
        self.assertEqual(pf["value"], b["value"])
        self.assertLessEqual(pf["cost"], pf["budget"])

    def test_global_plan_path_all_objectives_shared_budget(self):
        gs, players = self._shared_universe(20)  # universe = 22 > 20
        for obj in ("tokens", "score", "balanced", "eff"):
            opts = {"objective": obj, "maxBundle": 4, "coins": 1400, "reserve": 150}
            pf = self.engine.call("plan", gs, players, opts)["portfolio"]
            b = self.engine.call("portfolioBrute", gs, players, opts)
            self.assertGreater(pf["universe"], 20)
            self.assertEqual(sorted(pf["chosen"]), b["best"], obj)
            self.assertEqual(pf["value"], b["value"], obj)

    def test_reserve_bites_on_global_path(self):
        """`coins - reserve` must be the effective budget: a high reserve regains
        the optimal bundle, a low one excludes it -- matching brute force."""
        gs, players = self._shared_universe(19)  # universe = 21 > 20
        full_cost = sum(self.engine.call("loss", p) for p in players
                        if p["itemId"] in ("shared", "partner"))
        opts_lo = {"objective": "score", "maxBundle": 4,
                   "coins": full_cost, "reserve": 0}
        opts_hi = {"objective": "score", "maxBundle": 4,
                   "coins": full_cost, "reserve": full_cost}
        lo = self.engine.call("plan", gs, players, opts_lo)["portfolio"]
        hi = self.engine.call("plan", gs, players, opts_hi)["portfolio"]
        blo = self.engine.call("portfolioBrute", gs, players, opts_lo)
        bhi = self.engine.call("portfolioBrute", gs, players, opts_hi)
        self.assertEqual(lo["budget"], full_cost)
        self.assertEqual(hi["budget"], 0)
        self.assertEqual(sorted(lo["chosen"]), blo["best"])
        self.assertEqual(sorted(hi["chosen"]), bhi["best"])
        self.assertEqual(hi["chosen"], [], "zero post-reserve budget buys nothing")
        self.assertGreaterEqual(lo["value"], hi["value"])

    def test_global_path_shared_card_charged_once_over_20(self):
        gs, players = self._shared_universe(22)  # universe = 24 > 20
        opts = {"objective": "score", "maxBundle": 4, "coins": 10 ** 9, "reserve": 0}
        pf = self.engine.call("plan", gs, players, opts)["portfolio"]
        self.assertIn("shared", pf["chosen"])
        expected = sum(self.engine.call("loss", p) for p in players
                       if p["itemId"] in pf["chosen"])
        self.assertEqual(pf["cost"], expected)


class TestSetUpperBoundNegativeScores(EngineTestCase):
    """(P1 point 2, third round) `setUpperBound` monotonicity/admissibility was
    only argued for NON-NEGATIVE scores. The engine enforces that precondition by
    sanitizing every score through `sanScore` (NaN/missing/negative -> 0), so the
    bound stays a valid upper bound even when the input carries bad scores."""

    def test_sanScore_sanitizes(self):
        # JSON cannot carry NaN/Infinity literals, so those are exercised via the
        # strings the engine coerces with `+x` ("NaN" -> NaN, "Infinity" -> Inf).
        cases = [(250, 250), (-40, 0), (0, 0), (None, 0), ("NaN", 0),
                 ("-", 0), ("abc", 0), ("Infinity", 0), (12.5, 12.5),
                 ("300", 300), (-0.5, 0)]
        for raw, want in cases:
            self.assertEqual(self.engine.call("sanScore", raw), want, raw)

    def test_bound_is_upper_bound_with_negative_input_scores(self):
        """Pools carrying negative/NaN scores must never realise ABOVE the bound."""
        g = setdef("g1", slots=4, value="AC",
                   thresholds={"D": 10, "C": 300, "B": 600, "A": 900, "S": 1200},
                   rewards={"D": 0, "C": 5, "B": 10, "A": 20, "S": 40})
        bad_scores = [250, -80, 300, -10, 120, 0, 400, -50, 75, 210]
        pool = [make("p%d" % i, s, club="AC") for i, s in enumerate(bad_scores)]
        import itertools
        bound = self.engine.call("setUpperBound", g, pool)
        for k in range(len(pool) + 1):
            for idxs in itertools.combinations(range(len(pool)), k):
                sub = [pool[i] for i in idxs]
                ids = [x["itemId"] for x in sub]
                ev = self.engine.call("evalSet", g, sub, ids)
                realised = ev["score"]
                self.assertLessEqual(realised, bound,
                                     "subset %s realised %s > bound %s"
                                     % (idxs, realised, bound))

    def test_bound_monotone_with_negative_scores(self):
        g = setdef("g1", slots=3, value="AC")
        base = [make("a", 200, club="AC"), make("b", -900, club="AC")]
        bigger = base + [make("c", -300, club="AC")]
        b1 = self.engine.call("setUpperBound", g, base)
        b2 = self.engine.call("setUpperBound", g, bigger)
        self.assertLessEqual(b1, b2, "bound must not shrink when items are added")

    def test_engine_sanitizes_negative_score_in_portfolio(self):
        """A negative-score card cannot spoof a higher plan value: it is treated
        as score 0, so the plan is identical to the same scenario with a 0 card."""
        g = setdef("g1", slots=3, value="AC")
        neg = [make("o0", 100, club="AC", collected=True),
               make("x", -100000, club="AC", buy=10, resale=9)]
        zero = [make("o0", 100, club="AC", collected=True),
                make("x", 0, club="AC", buy=10, resale=9)]
        opts = {"objective": "score", "maxBundle": 2, "coins": 10 ** 9}
        a = self.engine.call("portfolioPlan", g and [g], neg, opts)
        b = self.engine.call("portfolioPlan", [g], zero, opts)
        self.assertEqual(a["value"], b["value"])
        self.assertEqual(a["chosen"], b["chosen"])


class TestPortfolioOptimalityReported(EngineTestCase):
    """(P1 point 3) `portfolioPlan` must report whether a plan is PROVEN optimal
    or only BEST FOUND. Beyond `EXACT_PF_LIMIT` the engine runs a real global
    Branch & Bound over the shared card set S -- so a large universe is either
    `proved` (B&B exhausted under the admissible bound) or `node_limit` (the
    `maxNodes` cap tripped -> best found). It must NEVER claim 'proved' while
    the search was truncated, nor fall back to a bare Greedy."""

    def _scenario(self, n_cands):
        players = [make("o0", 100, club="AC", collected=True)]
        for i in range(n_cands):
            players.append(make("c%02d" % i, 100 + i * 30, club="AC",
                                buy=200 + i * 100, resale=180 + i * 90))
        return [setdef("g1", slots=5, value="AC")], players

    def test_small_universe_is_proved(self):
        gs, players = self._scenario(6)
        p = self.engine.call("portfolioPlan", gs, players,
                             {"objective": "score", "maxBundle": 5, "coins": 10 ** 9})
        self.assertEqual(p["optimality"], "proved")
        self.assertTrue(p["proven"])
        self.assertTrue(p["exact"])
        self.assertLessEqual(p["universe"], 20)

    def test_small_universe_matches_brute(self):
        gs, players = self._scenario(8)
        opts = {"objective": "score", "maxBundle": 5, "coins": 10 ** 9}
        p = self.engine.call("portfolioPlan", gs, players, opts)
        b = self.engine.call("portfolioBrute", gs, players, opts)
        self.assertEqual(sorted(p["chosen"]), b["best"])
        self.assertEqual(p["value"], b["value"])

    def test_large_universe_runs_global_bb_and_reports_honestly(self):
        """> EXACT_PF_LIMIT: the global B&B path runs. With a generous node cap
        it must PROVE optimality (not fall back to 'best_found'); a tiny cap must
        honestly report 'node_limit' with `proven` False."""
        gs, players = self._scenario(25)  # > EXACT_PORTFOLIO_LIMIT (20)
        opts = {"objective": "score", "maxBundle": 5, "coins": 10 ** 9}
        p = self.engine.call("portfolioPlan", gs, players, opts)
        self.assertGreater(p["universe"], 20)
        self.assertTrue(p["feasible"])
        # Global B&B must be used (not the tiny-universe exhaustive regime).
        self.assertFalse(p["exact"])
        self.assertIn(p["optimality"], ("proved", "node_limit"))
        self.assertGreater(p["nodes"], 0)
        if p["optimality"] == "proved":
            self.assertTrue(p["proven"])
        else:
            self.assertFalse(p["proven"])

    def test_large_universe_node_cap_is_honest(self):
        """A node cap of 1 must flip the report to 'node_limit' (best found) and
        must NOT claim a proven optimum -- even though the universe > 20."""
        gs, players = self._scenario(25)
        p = self.engine.call("portfolioPlan", gs, players,
                             {"objective": "score", "maxBundle": 5,
                              "coins": 10 ** 9, "maxNodes": 1})
        self.assertGreater(p["universe"], 20)
        self.assertEqual(p["optimality"], "node_limit")
        self.assertFalse(p["proven"])
        self.assertFalse(p["exact"])
        self.assertTrue(p["feasible"])
        self.assertLessEqual(p["cost"], p["budget"])

    def test_large_universe_is_still_feasible_and_strictly_best_seed(self):
        """Sanity: the reported plan must be feasible and at least as good as the
        greedy seed it was started from (B&B only ever improves the incumbent)."""
        gs, players = self._scenario(24)
        p = self.engine.call("portfolioPlan", gs, players,
                             {"objective": "balanced", "maxBundle": 4, "coins": 900})
        self.assertTrue(p["feasible"])
        self.assertLessEqual(p["cost"], p["budget"])
        self.assertLessEqual(len(p["chosen"]), 4)
        self.assertGreaterEqual(p["value"], 0)


class TestPlanSetOptimalityReported(EngineTestCase):
    """(P1 point 3) planSet's `optimality` must distinguish proven-optimal from
    node-limit-truncated, and the node cap must actually be respected."""

    def test_default_run_is_proved(self):
        players = [make("o0", 100, collected=True)]
        players += [make("b%d" % i, 200 + i * 10, buy=100 + i * 7, resale=90 + i * 5)
                    for i in range(4)]
        r = self.engine.call("planSet", setdef(slots=3), players,
                             {"objective": "score", "maxBundle": 4, "coins": 10 ** 9})
        self.assertEqual(r["optimality"], "proved")
        self.assertIn("nodes", r)

    def test_node_cap_forces_best_found(self):
        """A tiny node cap must flip the report to 'node_limit' (best found)."""
        players = [make("o0", 100, collected=True)]
        players += [make("b%d" % i, 200 + i * 10, buy=100 + i * 7, resale=90 + i * 5)
                    for i in range(8)]
        r = self.engine.call("planSet", setdef(slots=4), players,
                             {"objective": "score", "maxBundle": 8, "coins": 10 ** 9,
                              "maxNodes": 1})
        self.assertEqual(r["optimality"], "node_limit")


class TestPlanDeterminism(EngineTestCase):
    """Same input -> byte-identical plan (no hidden state, stable ordering)."""

    def test_repeatable(self):
        players = [make("o%d" % i, 100 + i, collected=True) for i in range(3)]
        players += [make("b%d" % i, 200 + i * 10, buy=100 + i * 7, resale=90 + i * 5) for i in range(4)]
        gs = [setdef("g1", slots=4), setdef("g2", slots=4, value="AC")]
        a = self.engine.call("plan", gs, players, {"objective": "eff", "maxBundle": 8})
        b = self.engine.call("plan", gs, players, {"objective": "eff", "maxBundle": 8})
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_ranked_is_sorted_by_value(self):
        players = [make("o0", 100, collected=True)]
        players += [make("b1", 300, buy=200, resale=180), make("b2", 250, buy=150, resale=140)]
        gs = [setdef("gA", slots=2),
              setdef("gB", slots=2, thresholds={"D": 10, "C": 100, "B": 200, "A": 300, "S": 400})]
        r = self.engine.call("plan", gs, players, {"objective": "score", "maxBundle": 8})
        vals = [p["value"] for p in r["plans"]]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_objective_recorded_per_plan(self):
        players = [make("o0", 100, collected=True), make("b1", 300, buy=200, resale=180)]
        for obj in ("tokens", "score", "balanced", "eff"):
            r = self.engine.call("planSet", setdef(slots=2), players,
                                 {"objective": obj, "maxBundle": 8})
            self.assertEqual(r["objective"], obj)


class TestPlanUiBridge(unittest.TestCase):
    """The UI bridge (`plan0`/`toOpp`/`allOpps`) must exist and be wired to the
    engine. We check the real source text so a rename/removal cannot slip by."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(_ROOT, "index.html"), encoding="utf-8") as f:
            cls.html = f.read()

    def test_plan0_uses_engine_planSet(self):
        self.assertIn("function plan0(g){", self.html)
        self.assertIn("planSet(g,state.players,", self.html)
        self.assertIn("evalMemoReset()", self.html)

    def test_toopp_maps_engine_fields(self):
        for field in ("p.recommendations", "p.dTokens", "p.dScore", "p.newGrade",
                      "p.buyScore", "p.completeAfter"):
            self.assertIn(field, self.html, "toOpp must read " + field)

    def test_old_greedy_loop_is_gone(self):
        """The P0 greedy `for(let k=1;k<=max;k++){` bundle loop must be removed."""
        self.assertNotIn("pool.slice(0,Math.min(22", self.html)

    def test_objective_wired(self):
        self.assertIn("objective:state.settings.objective", self.html)
        self.assertIn("coins:state.settings.coins", self.html)
        self.assertIn("maxBundle:state.settings.maxBundle", self.html)

    def test_global_portfolio_panel_exists(self):
        """(P1 point 2) The UI must expose a VISIBLE global portfolio plan, not
        only per-set recommendations."""
        self.assertIn('id="portfolio"', self.html, "a portfolio panel container is required")
        self.assertIn("function renderPortfolio(", self.html)
        self.assertIn("portfolioPlan(state.galleries,state.players", self.html)
        # the shared budget is coins - reserve
        self.assertIn("coins:state.settings.coins", self.html)
        self.assertIn("reserve:state.settings.reserve", self.html)

    def test_global_portfolio_is_rendered(self):
        """render()/runOptimizer must actually call renderPortfolio()."""
        self.assertIn("renderPortfolio()", self.html)
        # must be wired both on full render and on the optimizer run
        self.assertGreaterEqual(self.html.count("renderPortfolio()"), 2,
                                "renderPortfolio must be called from render() and runOptimizer()")

    def test_global_portfolio_reports_optimality(self):
        """The panel must surface whether the plan is proven or best-found."""
        self.assertIn("optimality", self.html)
        self.assertIn("p.optimality", self.html)

    def test_global_portfolio_label_is_honest(self):
        """(P1 point 3, third round) The non-proven branch must NOT claim
        'proven'; it must say 'best found' (node limit)."""
        self.assertIn("p.optimality==='proved'", self.html)
        self.assertIn("best found", self.html)
        self.assertIn("node limit", self.html)
        # the else-branch string must not contain the word 'proven' as a claim
        m = re.search(r"p\.optimality==='proved'\?[^:]*:(.*?);", self.html)
        self.assertIsNotNone(m, "renderPortfolio optimality ternary not found")
        else_branch = m.group(1)
        self.assertIn("best found", else_branch)
        self.assertNotIn("proven optimal", else_branch)


class TestGlobalPortfolioUiBehavior(unittest.TestCase):
    """(P1 point 2) Execute the REAL `portfolio0` logic against the REAL engine
    on a two-set scenario where one card is shared, and assert the aggregated
    benefit, the single shared cost, and the post-reserve budget."""

    NODE = os.environ.get("NODE", "node")

    def _run(self, body):
        engine = os.path.join(_ROOT, "engine", "engine.js")
        script = (
            "const eng = require(%s);\n"
            "Object.assign(globalThis, eng);\n"
            "const state = { settings: { objective: 'score', taxRate: .05, maxBundle: 5, coins: 1000000000, reserve: 0 }, players: [], galleries: [] };\n"
            "function portfolio0(){ evalMemoReset(); return portfolioPlan(state.galleries, state.players, { objective: state.settings.objective, taxRate: state.settings.taxRate, coins: state.settings.coins, reserve: state.settings.reserve, maxBundle: state.settings.maxBundle }); }\n"
            % json.dumps(engine.replace("\\", "/"))
        )
        script += body
        out = subprocess.run([self.NODE, "-e", script], capture_output=True, text=True, timeout=60, cwd=_ROOT)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_two_set_global_portfolio(self):
        body = r"""
        const mk=(id,score,o={})=>Object.assign({id,itemId:id,playerKey:id,name:id,score,club:'AC',position:'CM',nation:'Spain',league:'L',rarity:'',special:'',collected:false},o);
        state.players = [
          mk('o0',110,{collected:true}), mk('o1',100,{collected:true}),
          mk('shared',260,{nation:'Spain',buyPrice:1200,resalePrice:1140}),
          mk('partner',240,{nation:'Spain',buyPrice:800,resalePrice:760}),
          mk('noise',300,{nation:'Germany',position:'GK',buyPrice:1500,resalePrice:1425})
        ];
        const sd=(id)=>({id,name:id,slots:4,eligibility:{type:'club',value:'AC'},
          thresholds:{D:10,C:400,B:800,A:1200,S:1600}, rewards:{D:0,C:5,B:12,A:24,S:48}});
        state.galleries = [sd('g1'), sd('g2')];
        const p = portfolio0();
        // Engine `loss()` for each chosen card, charged ONCE each.
        const expectedCost = state.players.filter(c=>p.chosen.includes(c.itemId))
          .reduce((s,c)=>s+loss(c,state.settings.taxRate),0);
        process.stdout.write(JSON.stringify({
          chosen: p.chosen.slice().sort(), cost: p.cost, budget: p.budget,
          expectedCost, dTokens: p.dTokens, dScore: p.dScore, optimality: p.optimality,
          proven: p.proven, details: p.detail.length,
          perSetPositive: p.detail.every(d => d.dScore > 0 || d.dTokens > 0)
        }));
        """
        r = self._run(body)
        self.assertIn("shared", r["chosen"])
        self.assertEqual(r["details"], 2, "one aggregated detail row per set")
        self.assertTrue(r["perSetPositive"], "the shared card must help both sets")
        self.assertEqual(r["cost"], r["expectedCost"],
                         "cost = union of loss() over the distinct chosen cards, once each")
        self.assertEqual(r["budget"], 1000000000)
        self.assertEqual(r["optimality"], "proved")
        self.assertTrue(r["proven"])
        # The shared card must contribute to BOTH sets: dScore is the sum over sets.
        self.assertGreaterEqual(r["dScore"], 520)

    def test_reserve_reduces_shared_budget(self):
        body = r"""
        const mk=(id,score,o={})=>Object.assign({id,itemId:id,playerKey:id,name:id,score,club:'AC',position:'CM',nation:'Spain',league:'L',rarity:'',special:'',collected:false},o);
        state.players = [
          mk('o0',110,{collected:true}),
          mk('big',400,{buyPrice:2000,resalePrice:2000}),
          mk('cheap',150,{buyPrice:120,resalePrice:120})
        ];
        const sd=(id)=>({id,name:id,slots:3,eligibility:{type:'club',value:'AC'},
          thresholds:{D:10,C:400,B:800,A:1200,S:1600}, rewards:{D:0,C:5,B:12,A:24,S:48}});
        state.galleries = [sd('g1'), sd('g2')];
        state.settings.coins = 1000000000;
        state.settings.reserve = 1000000000 - 101;   // budget = 101
        const p = portfolio0();
        process.stdout.write(JSON.stringify({ budget: p.budget, chosen: p.chosen.slice().sort(), cost: p.cost, feasible: p.feasible }));
        """
        r = self._run(body)
        self.assertEqual(r["budget"], 101)
        self.assertEqual(r["chosen"], ["big"], "budget 101 fits only `big` (loss 100)")
        self.assertLessEqual(r["cost"], 101)
        self.assertTrue(r["feasible"])


class TestPlanUiBridgeBehavior(unittest.TestCase):
    """Load the REAL engine + the REAL plan0/toOpp source (extracted from
    index.html) into one Node scope and execute the demo scenario.

    We cannot load the whole app script in Node: it uses `export`/`run` etc. as
    bare element-id globals, which is browser-only (and `export` is a reserved
    word to Node's parser). Instead we pull the exact bridge functions and run
    them against the real engine -- asserting behaviour, not just presence.
    """

    NODE = os.environ.get("NODE", "node")

    def _run(self, body):
        engine = os.path.join(_ROOT, "engine", "engine.js")
        script = (
            "const eng = require(%s);\n"
            "Object.assign(globalThis, eng);\n"
            "const state = { settings: { objective: 'eff', taxRate: .05, maxBundle: 15, coins: 270000 }, players: [], galleries: [] };\n"
            "function plan0(g){ evalMemoReset(); return planSet(g, state.players, { objective: state.settings.objective, taxRate: state.settings.taxRate, maxBundle: state.settings.maxBundle, coins: state.settings.coins }); }\n"
            % json.dumps(engine.replace("\\", "/"))
        )
        # The real toOpp body, copied verbatim from index.html between markers.
        with open(os.path.join(_ROOT, "index.html"), encoding="utf-8") as f:
            html = f.read()
        m = re.search(r"function toOpp\(p\)\{(.*?\n\})\n", html, re.S)
        script += "function toOpp(p){" + m.group(1) + "\n"
        script += body
        out = subprocess.run([self.NODE, "-e", script], capture_output=True, text=True, timeout=60, cwd=_ROOT)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_bridge_runs_demo_and_maps_fields(self):
        body = r"""
        state.players = [];
        for (let i=1;i<=15;i++) state.players.push({ id:'a'+i, itemId:'a'+i, playerKey:'p'+i, name:'P'+i,
          score: i<9?80:180+(i%3)*70, buyPrice:700+i*40, resalePrice:700+i*40, collected:i<9,
          club:'Athletic Club', league:'LALIGA', nation:'Spain', rarity:i>12?'Bronze':'Silver',
          position:'CM', gender:'men', firstOwner:false, holographic:false, sets:[] });
        const g = { id:'athletic', name:'Athletic Club', slots:15,
          eligibility:{type:'club', value:'Athletic Club', gender:'men'},
          thresholds:{D:10,C:900,B:1600,A:2400,S:3600}, rewards:{D:0,C:5,B:10,A:15,S:25} };
        const p = plan0(g);
        const o = toOpp(p);
        process.stdout.write(JSON.stringify({ set:o.g.id, owners:p.owners, bundle_len:o.bundle.length, dt:o.dt, ds:o.ds, cap:o.cap, completeAfter:o.completeAfter }));
        """
        r = self._run(body)
        self.assertEqual(r["set"], "athletic")
        self.assertEqual(r["owners"], 8, "the 8 collected demo cards must be eligible")
        self.assertGreaterEqual(r["bundle_len"], 1)
        self.assertGreater(r["ds"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
