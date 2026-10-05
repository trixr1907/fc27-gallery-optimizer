# Changelog

All notable changes to the FC 27 Gallery Optimizer, one entry per delivered
phase. Every entry corresponds to a real commit in this repository; the short
hash is given so the change can be inspected directly. (Phase 4, the tip, is the
one exception — see the note under it.)

The format follows [Keep a Changelog](https://keepachangelog.com/); the project
does not (yet) use semantic versioning — the phases are the delivery unit.

## [Unreleased]

Nothing yet.

## Phase 4 — 2026-10-05 — Completion: CI, smoke tests, deploy status

> The P4 commit is the tip of the `master` history. Its own hash is deliberately
> NOT quoted here: the changelog is edited by the same commit that delivers it, so
> quoting it would invalidate itself on every amend.

### Added
- `tools/check_all.py` — one command that runs everything CI runs (engine mirror
  byte-identity, `node --check`, the full suite) with a summary and timings.
  A missing Node is skipped, never a red failure.
- `.github/workflows/ci.yml` — CI on push/PR/manual dispatch (Python 3.13, Node
  22). **No `pip install` and no `npm install` anywhere.**
- `tests/test_smoke_server.py` — starts the **real** `server.py` on a free port
  and speaks real HTTP (health, the app, static assets, hardening headers,
  directory listing, traversal, the importer kill-switch).
- `tests/test_smoke_file.py` — boots the real `index.html` over `file://` in
  headless Chrome and drives the app's own entry points.
- `tests/test_render_manifest.py` — validates `render.yaml` structurally and runs
  its declared start command locally under Render's `PORT`/`HOST` contract.
- `tests/test_repo_hygiene.py` — pins the two closing reconciliations: the
  changelog records every phase commit, the missing `LICENSE` stays documented,
  and the `.gitignore` covers the benchmark/probe scratch.
- `CHANGELOG.md` (this file).

### Fixed
- **Security: the local server served dot-files and dot-directories.** `GET
  /.git/config` and `GET /.git/HEAD` returned **200**, exposing the repository's
  config and object database (i.e. the whole source history). Any path segment
  starting with `.` is now refused with **404** — not 403, so the response does
  not even confirm that the path exists. `..` is a dot-segment, so path traversal
  is now also refused with 404 by the same guard. Regression-tested in
  `tests/test_smoke_server.py`.

### Documented
- **The Render deploy is NOT verified.** `render.yaml` is a deploy-ready
  manifest; no deploy was performed. The disclaimer is asserted by tests in both
  `README.md` and `VERIFICATION.md` (§10.5) so it cannot be quietly dropped.
- The `file://` limitation: the FUT.GG importer is the `/api/futgg` server route,
  so it cannot work from disk. Everything else works fully offline.
- **No `LICENSE` is included**, deliberately — see "License" below.

## Phase 3 — 2026-10-05 (`1388934`) — Performance: cooperative search, virtualised UI

### Added
- A **cooperative step machine** for the whole portfolio search: the search is
  written as generators, so the UI advances it in ~20 ms slices and returns to
  the browser between them. `portfolioSearch(...)` exposes `step(msBudget)` and
  `extend(ms)`; the search **pauses** at its budget (state intact) and
  **resumes** for "Improve further" instead of recomputing.
- `tests/test_lineup_incremental.py`, `tests/test_portfolio_budget.py`.
- Benchmark tooling: `tools/bench_dataset.py` (frozen 127 × 3,000 dataset),
  `tools/bench_engine.py`, `tools/bench_browser.py`.

### Changed
- The interactive first run is **one global portfolio search with a shared total
  budget**, not 127 per-set searches. Measured cost split of the original 275 s:
  **127 × `planSet` = 282.5 s (≈ 96 %)**.
- The collection table is **virtualised** (a ~30-row window in the DOM, spacer
  rows, stable scroll container); the per-set summary is computed progressively.
- `lineup`/`evalSet`/the lazy base are **interruptible** (generators) so the
  search can yield *inside* a set evaluation.
- Per-set plans are computed **on demand**; the per-set breakdown loads lazily.

### Fixed
- The reported portfolio value was dominated by a ~9.25 × 10⁸ offset: the base
  used `score(pool.slice(0, slots))` (the first N owned) while the search
  evaluates the **lineup** (the best N). The base is now the capped lineup.
- `planSet`'s base had the same defect; the B&B incumbent could be worse than
  buying nothing; the `evalSet` memo key ignored the set's thresholds/rewards.

### Performance (frozen 127 × 3,000 dataset, identical seed)
- First calculation **277 s → 2.4 s**; longest synchronous browser block
  **2,340 ms → 22 ms**; initial render **4,340 ms → 35 ms**.

## Phase 2 — 2026-10-05 (`cb8beef`) — Parser integration + state/server layer

### Added
- Canonical **alias** layer, TTL **fetch cache**, **dated price snapshots**
  (`value` / `best` / `worst` / `priceUpdatedAt` / `source`, with a 30-day
  staleness warning), **schemaVersion 2 + forward migration**, **server
  hardening**, and an **import merge preview** with `verified`/`estimated`
  provenance and a manual-edit guard.
- A test module per concern, plus a UI/engine behaviour module that runs the
  shipped `index.html` functions against the real engine.

## Phase 1 — 2026-10-04 (`cfe0f6f`) — Shopping plan: Branch & Bound

### Added
- `planSet` is a real **Branch & Bound** over candidate card sets with an
  admissible monotone bound (`setUpperBound`), a greedy seed and a 2-opt
  refinement; every plan reports `proved` vs `node_limit` (*best found*).
- A **global portfolio plan** across all sets: each card is bought **once**, its
  cost charged **once**, against the shared budget `coins − reserve`.
- A dated, offline FUT.GG TAG-table fixture and its parser test.

### Fixed
- The B&B upper bound was unsound (`lineup()` is heuristic and not monotone in
  the pool); the eval-pool had to include candidates for a purchase to enter the
  lineup; the `evalSet` memo key had to include the resolved items.

## Phase 0 — 2026-10-04 (`b5db154`, `36fa5fb`) — Correctness harness

### Added
- The engine is exercised through the repository's own Node CLI
  (`tools/engine_cli.js`) with a byte-identical mirror (`tools/sync_engine.py`),
  plus offline fixtures and the first test modules.

### Fixed
- Parser and tag bugs found by running the real engine; the `export` reserved-word
  bug that stopped the inline script from ever executing.

## Baseline — 2026-10-04 (`a925878`)

The original pre-refactor state of the app, kept as the first commit so every
change above is reviewable as a diff.

---

## License

**No `LICENSE` file is included, deliberately.** Choosing a license is the
repository owner's legal decision, not a technical one, and this project has no
license granted by the original author either. Until the owner picks one, the
default applies: **all rights reserved**, and no permission is granted to copy,
modify or redistribute the code. If you intend to use this beyond personal use,
add the license you want and update this section.
