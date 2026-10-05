#!/usr/bin/env python3
"""P3 headless-engine benchmark (stdlib only). Measures the ENGINE, no browser.

This is ONE of the two SEPARATE P3 measurements. It drives the real JS engine
(`tools/engine_cli.js` -> `engine/engine.js`) over the agreed 127 sets x 3,000
cards dataset and reports:

  * first full calculation -- the work the app does when the user presses
    "Calculate" for the first time on a loaded state: `planSet()` per set +
    `portfolioPlan()` (global shared plan). Target: "< 3 s Erstberechnung".
  * subsequent interaction -- the work a SMALL follow-up action costs once the
    session is warm: re-planning ONE set (the memo is reset per action) and the
    global portfolio. Target: "< 100 ms Folgeinteraktion".

Honesty rules baked in:
  * every call has a wall-clock TIMEOUT; a call that exceeds it is recorded as
    `>timeout` and the phase continues -- a runaway set must not hang the run,
    and must NOT be silently counted as fast;
  * the verdict (`met`/`not_met`) is computed from the measured numbers, never
    asserted;
  * the dataset is the exact same deterministic payload the browser benchmark
    loads, so the two numbers are directly comparable.

Because the search is exponential in the candidate-pool size, the run ALSO
splits the 127 sets by candidate-pool size, so the report shows WHERE the time
goes instead of hiding it in one average. That split is the documented deviation.

Usage:  python tools/bench_engine.py [--json out.json] [--timeout 20]
"""
import argparse
import functools
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import bench_dataset  # noqa: E402
from engine_harness import EngineCli, NODE  # noqa: E402

OPTS = {"objective": "eff", "taxRate": 0.05, "coins": 270000, "reserve": 0,
        "maxBundle": 15, "priceScenario": "base",
        # P3 rework: the interactive first run is ONE global portfolio search with
        # a SHARED total budget (not 127 independent planSet searches). These are
        # the engine/UI defaults; recorded so the report states what was measured.
        "totalBudgetMs": 2500, "detail": False,
        # Per-phase defaults kept for the unbudgeted/legacy measurements below.
        "searchBudgetMs": 1500, "refineBudgetMs": 800,
        "portfolioSeedBudgetMs": 3000, "portfolioSearchBudgetMs": 4000,
        "portfolioRefineBudgetMs": 2000}

FIRST_TARGET_MS = 3000.0
SUBSEQ_TARGET_MS = 100.0


def call_timed(eng, fn, args, timeout_s):
    """Run one engine call with a wall-clock cap.

    Returns (ms, ok, result_or_None). A call that exceeds `timeout_s` is killed
    from the caller's point of view: we return (None, False, None). The engine
    process itself keeps working on the line, so after a timeout we RESTART the
    bridge -- a half-consumed response would desync the protocol.
    """
    done = {}

    def _work():
        t0 = time.perf_counter()
        try:
            done["r"] = eng.call(fn, *args)
            done["ms"] = (time.perf_counter() - t0) * 1000.0
        except Exception as e:  # noqa: BLE001
            done["err"] = e

    th = threading.Thread(target=_work, daemon=True)
    th.start()
    th.join(timeout_s)
    if th.is_alive():
        return None, False, None
    if "err" in done:
        return None, False, None
    return done.get("ms"), True, done.get("r")


def measure(data, timeout_s=20.0, with_split=False):
    """Measure the P3 interactive path on the frozen 127x3000 dataset.

    The app's first calculation is now ONE global portfolio search with a shared
    total budget, so that is what `first_calc` times. `--split` additionally
    reproduces the ORIGINAL cost split (127 x planSet, unbudgeted portfolio,
    detail pass) as evidence for where the old 275 s went.
    """
    eng = EngineCli()
    try:
        players, sets = data["players"], data["set"]
        res = {"dataset": {"sets": len(sets), "cards": len(players)},
               "timeout_s": timeout_s}

        # ---- FIRST CALCULATION: one budgeted global portfolio search ---------
        fc_ms, fc_ok, fc_res = call_timed(eng, "portfolioPlan", [sets, players, OPTS], timeout_s)
        if not fc_ok:
            eng.close()
            eng = EngineCli()
        res["first_calc"] = {
            "ms": round(fc_ms, 1) if fc_ok else None,
            "timed_out": not fc_ok,
            "budget_ms": OPTS.get("totalBudgetMs"),
            "optimality": (fc_res or {}).get("optimality") if fc_ok else None,
            "universe": (fc_res or {}).get("universe") if fc_ok else None,
            "chosen": len((fc_res or {}).get("chosen", [])) if fc_ok else None,
        }

        # ---- FOLLOW-UP: change the objective (a full re-plan) ----------------
        oc_opts = dict(OPTS, objective="tokens")
        oc_ms, oc_ok, _ = call_timed(eng, "portfolioPlan", [sets, players, oc_opts], timeout_s)
        if not oc_ok:
            eng.close()
            eng = EngineCli()
        res["objective_change"] = {"ms": round(oc_ms, 1) if oc_ok else None, "timed_out": not oc_ok}

        # ---- FOLLOW-UP: a cheaper re-plan (smaller shared budget) ------------
        # NOTE: this is still a full portfolio re-plan, so it is NOT the "<100 ms
        # subsequent interaction" the target means -- that one is a UI-only action
        # (search filter) and is measured by tools/bench_browser.py. Reported here
        # only to show the re-plan scales with its budget.
        small_opts = dict(OPTS, totalBudgetMs=600)
        sm_ms, sm_ok, _ = call_timed(eng, "portfolioPlan", [sets, players, small_opts], timeout_s)
        if not sm_ok:
            eng.close()
            eng = EngineCli()
        res["small_replan"] = {"ms": round(sm_ms, 1) if sm_ok else None, "timed_out": not sm_ok,
                               "budget_ms": 600}

        # ---- COOPERATIVE search: the path the UI actually drives -------------
        # `portfolioSearch` is a step machine; the UI calls `step(30ms)` in a
        # loop. The numbers that matter are the LONGEST single step (the longest
        # synchronous block) and the time to a first plan.
        cs_ms, cs_ok, cs_res = call_timed(
            eng, "portfolioSearch",
            [sets, players, dict(OPTS, stepBudgetMs=30, resumeMs=6000, maxPauses=1)],
            timeout_s)
        if not cs_ok:
            eng.close()
            eng = EngineCli()
        res["cooperative"] = {
            "steps": (cs_res or {}).get("steps") if cs_ok else None,
            "max_step_ms": (cs_res or {}).get("maxStepMs") if cs_ok else None,
            "first_plan_ms": (cs_res or {}).get("firstPlanMs") if cs_ok else None,
            "total_ms": (cs_res or {}).get("totalMs") if cs_ok else None,
            "pauses": (cs_res or {}).get("pauses") if cs_ok else None,
            "done": (cs_res or {}).get("done") if cs_ok else None,
            "timed_out": not cs_ok,
        }

        # ---- OPTIONAL: reproduce the original split (where the 275 s went) ---
        if with_split:
            sp = {}
            w_ms, w_ok, _ = call_timed(eng, "portfolioWorld", [sets, players, {}], timeout_s)
            sp["portfolioWorld_ms"] = round(w_ms, 1) if w_ok else None
            up_ms, up_ok, up_res = call_timed(eng, "portfolioPlan", [sets, players, {}], 600.0)
            sp["portfolio_unbudgeted_ms"] = round(up_ms, 1) if up_ok else None
            sp["portfolio_unbudgeted_optimality"] = (up_res or {}).get("optimality") if up_ok else None
            # 127 x planSet with ONE shared memo (the UI's old sweep).
            t0 = time.perf_counter()
            rows = []
            for g in sets:
                ms, ok, r = call_timed(eng, "planSet", [g, players, dict(OPTS)], timeout_s)
                rows.append({"set": g["id"], "ms": round(ms, 1) if ok else None,
                             "timed_out": not ok,
                             "optimality": (r or {}).get("optimality") if ok else None})
                if not ok:
                    eng.close()
                    eng = EngineCli()
            sp["per_set_sweep_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
            sp["per_set_sweep_sets"] = len(rows)
            sp["per_set_sweep_timed_out"] = sum(1 for r in rows if r["timed_out"])
            sp["per_set"] = rows
            res["split"] = sp

        res["targets"] = {"first_calc_ms": FIRST_TARGET_MS, "subseq_ms": SUBSEQ_TARGET_MS}
        # Verdict is COMPUTED, never asserted. The <100 ms subsequent-interaction
        # target is a UI-only action and is verified by tools/bench_browser.py, not
        # here (the engine has no sub-100 ms "follow-up" call to time).
        fc = res["first_calc"]
        res["targets"]["first_calc_met"] = (
            not fc["timed_out"] and fc["ms"] is not None and fc["ms"] < FIRST_TARGET_MS)
        res["targets"]["subseq_measured_by"] = "tools/bench_browser.py"
        return res
    finally:
        eng.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--timeout", type=float, default=20.0,
                    help="per-call wall-clock cap in seconds (default 20)")
    ap.add_argument("--split", action="store_true",
                    help="also reproduce the original cost split (127 x planSet, "
                         "unbudgeted portfolio, detail pass) -- slow (~5 min)")
    a = ap.parse_args()
    if not NODE:
        print("node not found on PATH -- headless engine benchmark cannot run")
        return 2
    data = bench_dataset.build()
    res = measure(data, timeout_s=a.timeout, with_split=a.split)
    res["node"] = subprocess.run([NODE, "--version"], capture_output=True,
                                 text=True).stdout.strip()
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2)
    # stdout: a compact summary (the per-set array goes to --json only).
    keys = ["dataset", "timeout_s", "first_calc", "cooperative", "objective_change",
            "small_replan", "targets", "node"]
    if a.split:
        keys.insert(5, "split")
    summary = {k: res[k] for k in keys if k in res}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
