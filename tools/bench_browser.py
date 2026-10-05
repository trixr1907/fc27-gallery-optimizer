#!/usr/bin/env python3
"""P3 browser-interaction benchmark (stdlib only). Measures the BROWSER, headless.

This is the SECOND, SEPARATE P3 measurement. Where `tools/bench_engine.py`
measures raw engine compute, this measures what the USER feels: a real headless
Chrome loads `index.html`, the 127x3000 state is injected, and we time the app's
own entry points with `performance.now()`:

  * first calculation -- the first `runOptimizer()` (all sets + portfolio +
    render). Target: "< 3 s Erstberechnung".
  * subsequent interaction -- a follow-up action on a warm page, e.g. changing a
    setting and re-running, or the search/collection re-render. Target:
    "< 100 ms Folgeinteraktion".

Chromium's `--headless` + `--dump-dom` cannot run timed JS and print a value, so
we use the standard trick: the page (a temporary harness that loads the real
index.html in an iframe, or the app itself via a small injected timing script)
writes its JSON result into `document.title`, and we parse it back with
`--dump-dom`. No npm package, no CDP client -- pure stdlib subprocess.

If Chrome is not found, the script reports that clearly and exits 3 (a SKIP, not
a failure). It never fabricates a browser number from the engine number.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import bench_dataset  # noqa: E402

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]

FIRST_TARGET_MS = 3000.0
SUBSEQ_TARGET_MS = 100.0


def find_chrome():
    env = os.environ.get("FC27_CHROME")
    if env and os.path.exists(env):
        return env
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    for name in ("google-chrome", "chrome", "chromium"):
        w = shutil.which(name)
        if w:
            return w
    return None


def build_harness(state_json):
    """A bootstrap <script> injected into a COPY of index.html, right before
    </body>, that drives the app's own entry points and writes the timing JSON
    into `document.title` for `--dump-dom`.

    Why injection instead of an iframe wrapper: on this Chrome build the
    iframe + `--virtual-time-budget` combination never fires the iframe's
    `onload` under headless `--dump-dom`, so the run hangs. Injecting into the
    page itself runs in the same document, on the same load event the app
    already works in, and completes deterministically. index.html itself is
    never modified -- only the throwaway copy is.

    The injection runs in TWO parts:
      * a HEAD script that writes the benchmark state into localStorage BEFORE
        the app's own script runs -- so the app boots with the 127x3000 state
        already present (setting it afterwards would be too late: the app calls
        `load()` at parse time and keeps the result in `state`);
      * a BODY script (before </body>, after the app) that re-renders and drives
        the app's real entry points, timing them with `performance.now()`.
    index.html itself is never modified -- only the throwaway copy is.
    """
    head = ("<script>try{localStorage.setItem('fc27gallery.v2',"
            "JSON.stringify(__STATE__))}catch(e){document.title='FC27BENCH:'"
            "+JSON.stringify({errors:['storage:'+e.message]})}</script></head>")
    driver = r"""
<script>
(function () {
  var out = { errors: [] };
  function setTitle(o) { document.title = 'FC27BENCH:' + JSON.stringify(o); }
  function t(fn) { var a = performance.now(); try { fn(); } catch (e) { out.errors.push('t:' + e.message); } return performance.now() - a; }
  try {
    // The app booted with the injected state already in localStorage, so `state`
    // is the 127x3000 payload. Report its shape, then drive the real entry points.
    out.players = state.players.length;
    out.galleries = state.galleries.length;

    // ---- RENDER -------------------------------------------------------------
    // `render()` now paints immediately: the per-set evaluation runs in
    // progressive batches (renderSummaryChunked), so the synchronous cost is the
    // DOM only. `summary_total_ms` is the TOTAL work that pass does in the
    // background (measured separately, informational).
    out.render_ms = t(function () { render(); });
    // Virtualisation proof: how many player rows are actually in the DOM.
    out.dom_player_rows = document.querySelectorAll('#playersScroll tbody tr.prow').length;
    out.dom_total_players = state.players.length;
    var _t = performance.now();
    for (var _i = 0; _i < state.galleries.length; _i++) { evalG(state.galleries[_i], state.players); }
    out.summary_total_ms = performance.now() - _t;

    // ---- FIRST CALCULATION: the COOPERATIVE search, advanced in slices ------
    // This is exactly what the UI does: `step(SEARCH_SLICE_MS)` in a loop, with a
    // paint between slices. The metric that matters is the LONGEST single slice
    // (the longest synchronous block), plus how long until a first plan exists
    // and how long the whole search takes.
    function drive(search, totalCapMs) {
      var t0 = performance.now(), steps = 0, maxTick = 0, firstPlan = null, paused = false, done = false;
      var r = search.step(SEARCH_SLICE_MS);
      while (!r.done && !r.paused && performance.now() - t0 < totalCapMs) {
        if (firstPlan === null && r.progress && r.progress.best && r.progress.best.length) firstPlan = performance.now() - t0;
        var a = performance.now();
        r = search.step(SEARCH_SLICE_MS);
        var dt = performance.now() - a;
        steps++;
        if (dt > maxTick) maxTick = dt;
      }
      paused = !!r.paused; done = !!r.done;
      return { steps: steps, maxTick: maxTick, firstPlan: firstPlan, paused: paused, done: done,
               total: performance.now() - t0, progress: r.progress, plan: r.plan };
    }
    var s1 = portfolioSearch(state.galleries,state.players,optOpts({totalBudgetMs:OPT_INTERACTIVE_MS}));
    var d1 = drive(s1, 30000);
    out.first_calc_ms = d1.total;                 // TOTAL search time (sum of slices)
    out.search_max_tick_ms = d1.maxTick;          // LONGEST single synchronous block
    out.search_first_plan_ms = d1.firstPlan;      // time to a first "best found" plan
    out.search_steps = d1.steps;
    out.search_paused = d1.paused;
    out.first_calc_optimality = d1.plan ? d1.plan.optimality : 'node_limit';
    out.first_calc_chosen = d1.progress && d1.progress.best ? d1.progress.best.length : null;

    // ---- FOLLOW-UP: change the OBJECTIVE (a FULL re-plan) -------------------
    var s2 = portfolioSearch(state.galleries,state.players,optOpts({objective:(state.settings.objective==='eff')?'tokens':'eff',totalBudgetMs:OPT_INTERACTIVE_MS}));
    var d2 = drive(s2, 30000);
    out.objective_change_ms = d2.total;
    out.objective_change_max_tick_ms = d2.maxTick;

    // ---- FOLLOW-UP: "Improve further" RESUMES the first search -------------
    if (s1 && !s1.done) { s1.extend(OPT_IMPROVE_MS); }
    var d3 = s1 && !s1.done ? drive(s1, OPT_IMPROVE_MS + 5000) : { total: 0, maxTick: 0 };
    out.improve_ms = d3.total;
    out.improve_max_tick_ms = d3.maxTick;
    out.improve_resumed = !!(s1 && !s1.done) || d3.steps > 0;

    // ---- FOLLOW-UP: a CHEAP action (search filter re-render) ----------------
    var s = document.getElementById('playerSearch');
    if (s) { s.value = 'a'; out.subseq_ms = t(function () { s.oninput(); }); }
    out.dom_player_rows_filtered = document.querySelectorAll('#playersScroll tbody tr.prow').length;

    // Render the result so the DOM shows a real plan too.
    renderPortfolio(out.first_calc_ms, OPT_INTERACTIVE_MS);
    var ps = document.getElementById('portfolio');
    out.portfolio_len = ps ? (ps.innerHTML || '').length : null;
    // The WORST main-thread block any of the actions above caused.
    // The WORST synchronous block is now the longest search SLICE, not the total.
    var blocks = [out.render_ms, out.search_max_tick_ms, out.objective_change_max_tick_ms, out.improve_max_tick_ms]
      .filter(function (v) { return typeof v === 'number'; });
    out.max_block_ms = Math.max.apply(null, blocks);
  } catch (e) { out.errors.push('drive:' + e.message); }
  out.targets = {
    first_calc_ms: 3000, subseq_ms: 100, objective_change_ms: 3000,
    first_calc_met: out.first_calc_ms != null && out.first_calc_ms < 3000,
    subseq_met: out.subseq_ms != null && out.subseq_ms < 100,
    objective_change_met: out.objective_change_ms != null && out.objective_change_ms < 3000,
    dom_rows_bounded: out.dom_player_rows != null && out.dom_player_rows < 300
  };
  setTitle(out);
})();
</script>
</body>"""
    return head.replace("__STATE__", state_json), driver.replace("__STATE__", state_json)


def run_browser(state, chrome, timeout=180):
    tmp = tempfile.mkdtemp(prefix="fc27bench_")
    src = os.path.join(ROOT, "index.html")
    with open(src, "r", encoding="utf-8") as fh:
        html = fh.read()
    # Inject the state BEFORE the app's script (head) and the driver after it.
    head, driver = build_harness(json.dumps(state, separators=(",", ":")))
    if "</head>" in html:
        html = html.replace("</head>", head, 1)
    if "</body>" in html:
        html = html.replace("</body>", driver, 1)
    else:
        html = html + driver
    hpath = os.path.join(tmp, "index.html")
    with open(hpath, "w", encoding="utf-8") as fh:
        fh.write(html)
    profile = os.path.join(tmp, "profile")
    # No `--virtual-time-budget`: it freezes `performance.now()` during a
    # synchronous block, which would make the timings meaningless. The driver is
    # synchronous (it calls the app's bounded compute directly), so it finishes
    # before the load event and `--dump-dom` captures the result.
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--disable-dev-shm-usage", "--allow-file-access-from-files",
           "--user-data-dir=" + profile,
           "--dump-dom", "file:///" + hpath.replace("\\", "/")]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "chrome timed out after %ss" % timeout}
    m = re.search(r"FC27BENCH:(\{.*?\})</title>", proc.stdout, re.S)
    if not m:
        return {"ok": False, "error": "no benchmark title found",
                "stdout_head": (proc.stdout or "")[:400],
                "stderr_head": (proc.stderr or "")[:400]}
    try:
        res = json.loads(m.group(1))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "bad JSON: %s" % e, "raw": m.group(1)[:400]}
    res["ok"] = True
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--timeout", type=int, default=600,
                    help="per-run Chrome wall-clock cap (default 600s; the full "
                         "127x3000 first calculation is bounded by the engine's "
                         "per-set search/refine budgets)")
    ap.add_argument("--sets", type=int, default=bench_dataset.SETS,
                    help="number of Gallery sets (default 127; lower for a smoke test)")
    ap.add_argument("--cards", type=int, default=bench_dataset.CARDS,
                    help="number of cards (default 3000; lower for a smoke test)")
    a = ap.parse_args()
    chrome = find_chrome()
    if not chrome:
        print(json.dumps({"ok": False, "error": "Chrome not found",
                          "hint": "set FC27_CHROME to the chrome executable"}))
        return 3
    state = bench_dataset.build_state(cards=a.cards, sets=a.sets)
    res = run_browser(state, chrome, timeout=a.timeout)
    res["chrome"] = chrome
    res["dataset"] = {"sets": len(state["galleries"]), "cards": len(state["players"])}
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2)
    print(json.dumps(res, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
