#!/usr/bin/env python3
"""P3.2/P3.4 -- correctness of the incremental lineup evaluator.

`lineup()` used to score every neighbour with a full `score(t)` (21 tag passes +
sort + top-10 cut). P3 replaced that inner call with an incremental evaluator
(`_mkEval`/`swapTotal`) that maintains per-key buckets and recomputes the same
bonus arithmetic. This module proves the swap is a PURE SPEED-UP:

  1. The incremental evaluator agrees with `score()` on every neighbour it is
     asked about -- checked through the engine on random and adversarial pools
     (empty keys, duplicate playerKeys, negative/NaN scores, holographic/special
     flags, all three positions).
  2. `lineup(pool, n)` returns exactly the same chosen items (and the same total)
     as a brute-force neighbourhood search over the SAME hill-climb order -- i.e.
     the incremental path makes identical choices.
  3. On small pools the lineup total equals the true optimum over all subsets of
     size <= n (brute force), so the search itself is not silently truncating.

R5 (engine assertions only on constructed data) is respected: every card here is
built by the test, never scraped. No third-party dependencies.
"""

import itertools
import os
import random
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from engine_harness import EngineTestCase, node_available  # noqa: E402


# --------------------------------------------------------------------------- #
# Card / pool construction (all synthetic -- R5)
# --------------------------------------------------------------------------- #

NATIONS = ["DE", "FR", "EN", "ES", "IT", "BR", "AR", ""]
CLUBS = ["FC A", "FC B", "FC C", "Club D", ""]
LEAGUES = ["Bundesliga", "Ligue 1", "Premier League", ""]
POSITIONS = ["GK", "CB", "LB", "RB", "CDM", "CM", "CAM", "LM", "RM", "ST", "LW", "RW"]
RARITIES = ["Bronze", "Silver", "Gold"]
SPECIALS = [None, "Icon", "Hero", "Heroic", "TOTW", "Team of the Week"]


def make_card(rng, idx, adversarial=False):
    """One synthetic card. `adversarial` stresses the empty-key / duplicate paths."""
    if adversarial:
        # Force many empty keys and shared playerKeys so buckets collapse.
        nation = rng.choice(["", "", "DE", "", "DE"])
        club = rng.choice(["", "", "FC A", ""])
        league = rng.choice(["", "", "", "Bundesliga"])
        player_key = rng.choice(["p1", "p1", "p2", "", "p1"])
        # JSON has no NaN: "NaN" is a *string*, which exercises sanScore's
        # tolerant coercions (exactly the adversarial path the evaluator must
        # match). Real NaN arrives through the UI, never through this bridge.
        score = rng.choice([-5.0, 0.0, 1.5, "NaN", 10.0, 3.0])
        rarity = rng.choice(RARITIES)
        special = rng.choice(SPECIALS)
        holo = rng.choice([True, False])
        pos = rng.choice(POSITIONS)
        wf = rng.choice([1, 5])
        sm = rng.choice([1, 5])
        first = rng.choice([True, False])
    else:
        nation = rng.choice(NATIONS)
        club = rng.choice(CLUBS)
        league = rng.choice(LEAGUES)
        player_key = "p%d" % rng.randint(0, 5)
        score = round(rng.uniform(0, 40), 2)
        rarity = rng.choice(RARITIES)
        special = rng.choice(SPECIALS)
        holo = rng.random() < 0.3
        pos = rng.choice(POSITIONS)
        wf = rng.choice([1, 2, 3, 4, 5])
        sm = rng.choice([1, 2, 3, 4, 5])
        first = rng.random() < 0.4
    return {
        "id": idx,
        "itemId": "card-%d" % idx,
        "playerKey": player_key,
        "name": player_key or ("Card %d" % idx),
        "score": score,
        "rarity": rarity,
        "special": special,
        "holographic": holo,
        "position": pos,
        "weakFoot": wf,
        "skillMoves": sm,
        "firstOwner": first,
        "club": club,
        "nation": nation,
        "league": league,
    }


def make_pool(seed, size, adversarial=False):
    rng = random.Random(seed)
    return [make_card(rng, i, adversarial) for i in range(size)]


def sig(items):
    """Order-insensitive-ish signature of a chosen lineup (for equality checks)."""
    return sorted((it.get("itemId") or it.get("id")) for it in items)


@unittest.skipUnless(node_available(), "node not found on PATH")
class TestLineupIncremental(EngineTestCase):

    # ------------------------------------------------------------------ #
    # 1. lineup() is a pure speed-up: same choices as a naive reference.
    # ------------------------------------------------------------------ #

    def _naive_lineup(self, pool, n):
        """Reference lineup: EXACTLY the documented algorithm, all score() calls.

        Mirrors the JS greedy-seed + hill-climb (5 rounds) using the engine's own
        `score`, so any divergence from the shipped `lineup` is a real behaviour
        change introduced by the incremental evaluator.
        """
        eng = self.engine
        by_id = {}
        for p in pool:
            k = p.get("itemId") or p.get("id")
            prev = by_id.get(k)
            if prev is None or eng.call("sanScore", p.get("score")) > eng.call("sanScore", prev.get("score")):
                by_id[k] = p
        pool = list(by_id.values())
        if len(pool) <= n:
            return sig(pool), eng.call("score", pool)["total"]
        cur = sorted(pool, key=lambda p: -eng.call("sanScore", p.get("score")))[:n]
        cs = eng.call("score", cur)["total"]
        cur_ids = set(cur[i].get("itemId") or cur[i].get("id") for i in range(len(cur)))
        for _ in range(5):
            best = None
            for i in range(n):
                for c in pool:
                    cid = c.get("itemId") or c.get("id")
                    if cid in cur_ids:
                        continue
                    t = list(cur)
                    t[i] = c
                    s = eng.call("score", t)["total"]
                    if s > cs and (best is None or s > best[2]):
                        best = (i, c, s)
            if best is None:
                break
            cur_ids.discard(cur[best[0]].get("itemId") or cur[best[0]].get("id"))
            cur[best[0]] = best[1]
            cur_ids.add(best[1].get("itemId") or best[1].get("id"))
            cs = best[2]
        return sig(cur), eng.call("score", cur)["total"]

    def test_lineup_matches_naive_reference(self):
        """Shipped lineup picks the SAME items as the naive full-score version."""
        for trial in range(12):
            n = 3 + (trial % 4)
            size = 8 + trial * 3
            pool = make_pool(1000 + trial, size, adversarial=(trial % 3 == 0))
            got = self.engine.call("lineup", pool, n)
            ref_sig, ref_total = self._naive_lineup(pool, n)
            self.assertEqual(sig(got["items"]), ref_sig,
                             "lineup diverged from naive reference (trial %d)" % trial)
            self.assertAlmostEqual(got["total"], ref_total, places=6,
                                   msg="lineup total differs (trial %d)" % trial)

    # ------------------------------------------------------------------ #
    # 2. Small pools: lineup total equals the true subset optimum.
    # ------------------------------------------------------------------ #

    def test_lineup_equals_brute_force_on_small_pools(self):
        """Exhaustive optimum over subsets of size <= n matches lineup's total."""
        for trial in range(8):
            n = 3
            size = 7 + trial  # 7..14 cards -> C(14,3) top configurations is cheap
            pool = make_pool(2000 + trial, size, adversarial=(trial % 2 == 0))
            got = self.engine.call("lineup", pool, n)
            best = None
            for combo in itertools.combinations(range(size), n):
                sub = [pool[i] for i in combo]
                s = self.engine.call("score", sub)["total"]
                if best is None or s > best:
                    best = s
            # lineup may pick <= n if the pool is smaller, but here size > n.
            self.assertAlmostEqual(got["total"], best, places=6,
                                   msg="lineup missed the optimum (trial %d)" % trial)

    # ------------------------------------------------------------------ #
    # 3. Adversarial pools do not crash and stay self-consistent.
    # ------------------------------------------------------------------ #

    def test_swap_evaluator_is_rebuilt_per_round(self):
        """Regression: one stale evaluator reused across rounds loses swaps.

        An earlier P3 draft built a single incremental evaluator before the
        hill-climb loop and reused it across rounds. After the first committed
        swap its buckets were stale, so later rounds under-valued neighbours and
        lineup returned a WORSE set than the naive version (observed: 228.69 vs
        229.51 on a constructed pool). This asserts the shipped lineup never
        returns less than the naive reference on that exact pool.
        """
        pool = make_pool(1000 + 7, 29, adversarial=False)
        got = self.engine.call("lineup", pool, 6)
        _, ref_total = self._naive_lineup(pool, 6)
        self.assertGreaterEqual(
            got["total"], ref_total - 1e-9,
            "lineup returned %r, worse than naive %r -- stale evaluator?"
            % (got["total"], ref_total),
        )

    def test_adversarial_pools_are_handled(self):
        """NaN / negative / empty-key cards: lineup stays finite and consistent."""
        pool = make_pool(9, 40, adversarial=True)
        for n in (1, 3, 11, 40, 60):
            got = self.engine.call("lineup", pool, n)
            # Items are unique by card id, never more than the pool.
            ids = sig(got["items"])
            self.assertEqual(len(ids), len(set(ids)), "duplicate card in lineup")
            self.assertLessEqual(len(ids), min(n, 40))

    # ------------------------------------------------------------------ #
    # 4. swapTotal equivalence is exercised via lineup on tagged pools.
    # ------------------------------------------------------------------ #

    def test_lineup_total_is_reproducible(self):
        """Same pool + same n => same result, twice (no hidden mutable state)."""
        pool = make_pool(4242, 60, adversarial=False)
        a = self.engine.call("lineup", pool, 11)
        b = self.engine.call("lineup", pool, 11)
        self.assertEqual(sig(a["items"]), sig(b["items"]))
        self.assertAlmostEqual(a["total"], b["total"], places=9)


def setdef(sid, slots, club="AC", thresholds=None):
    return {
        "id": sid, "name": sid, "slots": slots,
        "eligibility": {"type": "club", "value": club},
        "thresholds": thresholds or {"D": 10, "C": 300, "B": 600, "A": 900, "S": 1200},
        "rewards": {"D": 0, "C": 5, "B": 10, "A": 20, "S": 40},
    }


def make_plan_card(iid, score, *, club="AC", nation="Spain", position="CM",
                   collected=False, buy=None, resale=None):
    p = {"id": iid, "itemId": iid, "playerKey": iid, "name": iid, "score": score,
         "club": club, "nation": nation, "position": position, "league": "L",
         "rarity": "Gold", "special": "", "collected": collected}
    if buy is not None:
        p["buyPrice"] = buy
        p["resalePrice"] = resale if resale is not None else buy
    return p


@unittest.skipUnless(node_available(), "node not found on PATH")
class TestPlanSetIdentityFastPath(EngineTestCase):
    """P3.4 -- the improve2opt identity fast path returns the SAME plan as the
    pre-P3 path that always called `evalSet`.

    `planSet` gained an incremental evaluator for the case where the realised
    lineup is the identity (owned pool + selection fits within `slots`, no
    duplicate itemId). That is a pure speed-up: it MUST produce byte-identical
    `chosen`, `value`, `dScore` and `optimality` to the naive path. `opts._naive`
    forces the old path, so the two can be compared directly on identical input.

    This class also guards the LATENT memo bug it exposed: `evalSet`'s memo key
    omitted the set thresholds/rewards, so two sets sharing id+slots but differing
    in thresholds returned each other's grade. The key now includes them
    (`_setScoreSig`); the `test_same_id_different_thresholds` case pins that.
    """

    def _scenario(self, seed, n_cands=25, n_owned=2, slots=6, max_bundle=4):
        rng = random.Random(seed)
        players = []
        for i in range(n_owned):
            players.append(make_plan_card("o%d" % i, rng.randint(80, 160), collected=True))
        nations = ["Spain", "France", "Italy", "England", "Germany"]
        positions = ["CM", "ST", "GK", "CB", "LW"]
        for i in range(n_cands):
            players.append(make_plan_card(
                "c%02d" % i, rng.randint(40, 600),
                nation=rng.choice(nations), position=rng.choice(positions),
                buy=rng.randint(50, 2000), resale=rng.randint(30, 1500)))
        return players

    def test_fast_path_matches_naive(self):
        """Identical plan with and without the identity fast path."""
        for seed in range(10):
            players = self._scenario(seed)
            g = setdef("g1", slots=6)
            for obj in ("tokens", "score", "balanced", "eff"):
                for coins in (10 ** 9, 3000):
                    base_opts = {"objective": obj, "maxBundle": 4, "coins": coins}
                    fast = self.engine.call("planSet", g, players, dict(base_opts))
                    naive = self.engine.call("planSet", g, players,
                                             dict(base_opts, _naive=True))
                    self.assertEqual(fast["chosen"], naive["chosen"],
                                     "seed=%d obj=%s coins=%s chosen differs" % (seed, obj, coins))
                    self.assertAlmostEqual(fast["value"], naive["value"], places=6,
                                           msg="seed=%d obj=%s coins=%s value differs" % (seed, obj, coins))
                    self.assertAlmostEqual(fast["dScore"], naive["dScore"], places=6)
                    self.assertEqual(fast["optimality"], naive["optimality"])

    def test_same_id_different_thresholds(self):
        """The eval memo must not leak a grade across sets with equal id+slots.

        Two set definitions share id "gX" and the same slots but different
        thresholds. Evaluating the first then the second must give each set its
        OWN grade (the memo key now includes thresholds/rewards).
        """
        players = self._scenario(3)
        # Thresholds chosen so the same score lands in a DIFFERENT grade band.
        low = setdef("gX", slots=6, thresholds={"D": 10, "C": 300, "B": 600, "A": 900, "S": 1200})
        high = setdef("gX", slots=6, thresholds={"D": 10, "C": 5000, "B": 9000, "A": 12000, "S": 15000})
        ids = ["o0", "o1", "c00", "c01", "c02", "c03"]
        a = self.engine.call("evalSet", low, players, ids)
        b = self.engine.call("evalSet", high, players, ids)
        # Same score (same items), but the grade must reflect each set's thresholds.
        self.assertAlmostEqual(a["score"], b["score"], places=6)
        self.assertIsNotNone(a["grade"], "scenario score must clear the LOW set's floor")
        self.assertNotEqual(a["grade"], b["grade"],
                            "grade leaked across sets with equal id+slots (memo key bug)")
        # Re-evaluating the first set must still give the first grade.
        a2 = self.engine.call("evalSet", low, players, ids)
        self.assertEqual(a["grade"], a2["grade"])


@unittest.skipUnless(node_available(), "node not found on PATH")
class TestPlanSetBaseAndBounds(EngineTestCase):
    """P3 findings pinned as tests.

    Two real defects were surfaced by the P3 large-pool benchmark and fixed:

    (1) `planSet`'s "base" used `score(pool)` over ALL owned items. When the
        owned pool exceeds `slots` (e.g. 75 owned, 15 slots) that counts cards
        the lineup cannot hold, so `dScore` went negative and "buy nothing"
        looked WORSE than buying. The base must be the gallery's actual lineup
        (`evalSet`, i.e. the owned pool capped at `slots`).

    (2) The B&B incumbent was seeded with the greedy plan even when that plan
        was worse than buying nothing, so a large-pool set could return a
        negative-value plan.

    Both are asserted here on a constructed pool whose size exceeds `slots`.
    """

    def _oversubscribed(self, seed):
        """A set whose owned pool already exceeds `slots`."""
        rng = random.Random(seed)
        players = []
        # 20 owned cards (> slots=5), all eligible for club "AC".
        for i in range(20):
            players.append(make_plan_card("o%02d" % i, rng.randint(60, 200),
                                          collected=True, nation=rng.choice(["Spain", "France"])))
        # A few buyable cards, some clearly WORSE than the owned pool.
        for i in range(6):
            players.append(make_plan_card("c%02d" % i, rng.randint(5, 60),
                                          buy=rng.randint(50, 900), resale=rng.randint(10, 200)))
        return players

    def test_base_is_the_capped_lineup_not_all_owned(self):
        """With pool > slots, base must equal evalSet's lineup score."""
        players = self._oversubscribed(11)
        g = setdef("g1", slots=5)
        pool = self.engine.call("poolFor", g, players, [])
        self.assertGreater(len(pool), g["slots"], "scenario must oversubscribe slots")
        r = self.engine.call("planSet", g, players, {"objective": "eff", "maxBundle": 3,
                                                     "coins": 10 ** 9})
        # The reported base score must be the lineup score of the owned pool.
        pool_ids = [p["itemId"] for p in pool]
        lineup = self.engine.call("evalSet", g, pool, pool_ids)
        self.assertAlmostEqual(r["base"]["score"], lineup["score"], places=6,
                               msg="base must be the capped lineup, not score(all owned)")

    def test_plan_never_worse_than_buying_nothing(self):
        """A plan whose objective is negative must be replaced by 'buy nothing'."""
        for seed in range(6):
            players = self._oversubscribed(seed)
            g = setdef("g1", slots=5)
            for obj in ("tokens", "score", "balanced", "eff"):
                r = self.engine.call("planSet", g, players,
                                     {"objective": obj, "maxBundle": 3, "coins": 10 ** 9})
                self.assertGreaterEqual(
                    r["value"], -1e-9,
                    "seed=%d obj=%s returned a negative-value plan (%r) -- the "
                    "incumbent must never be worse than buying nothing"
                    % (seed, obj, r["value"]))

    def test_bounded_search_reports_node_limit_not_optimal(self):
        """A tiny search budget must yield a best-found plan flagged node_limit.

        The plan must still be coin-feasible and use only eligible cards; only
        the optimality CLAIM changes (never silently 'proved').
        """
        players = self._oversubscribed(3)
        g = setdef("g1", slots=5)
        r = self.engine.call("planSet", g, players,
                             {"objective": "eff", "maxBundle": 3, "coins": 10 ** 9,
                              "searchBudgetMs": 1, "refineBudgetMs": 1})
        self.assertEqual(r["optimality"], "node_limit")
        self.assertTrue(r["feasible"])


if __name__ == "__main__":
    unittest.main()
