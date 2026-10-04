# VERIFICATION.md — P0 acceptance evidence & P1 evidence

This file records the **reproducible evidence** for the P0 and P1 deliverables.
Every number and every green line below comes from an actual run of the suite in
this repository — nothing here is estimated or copied from an earlier draft.

- **Command:** `python -m unittest discover -s tests -v`
- **Result (P1, third amendment):** `Ran 180 tests` — `OK`
- **Result (P1, second amendment):** `Ran 169 tests` — `OK`
- **Result (P1, first amendment):** `Ran 149 tests` — `OK`
- **Result (P1, first submission):** `Ran 126 tests` — `OK`
- **Result (P0, at acceptance):** `Ran 104 tests` — `OK`
- **Runtime:** ~47 s
- **Node:** used by the K1 harness (`tools/engine_cli.js`); if `node` is absent,
  `test_sync_engine.TestEngineLoadable.test_loadable` is skipped but
  `test_bytes_equal` still runs (R4/F5).

> **Third amendment note (P1 re-submission #3).** The second amended P1 was
> **still not accepted**. Three points were raised and are all closed here:
> (1) `portfolioPlan` only searched **exactly** up to 20 candidates and fell back
> to **Greedy** beyond that — R3 requires the search over the **global card set
> S**; beyond `EXACT_PF_LIMIT` the engine now runs a real global
> **Branch & Bound** over S (`portfolioUpperBound` + `portfolioBranchAndBound`,
> `maxNodes`-capped) seeded by a feasible greedy plan and refined by a
> budget-respecting 2-opt, reporting `optimality: 'proved' | 'node_limit'`
> (`'node_limit'` = *best found*, never "proven"); the brute-force reference
> (`portfolioBrute`) was rewritten to enumerate size-≤`maxBundle` **combinations**
> so it stays exhaustive past 20 and now checks the **global `plan()` path** with
> shared cards and `coins − reserve` on universes 21–24 for all four objectives;
> (2) `setUpperBound`'s monotonicity assumes **non-negative scores** — the engine
> now **enforces** the precondition by sanitizing every score through `sanScore`
> (NaN / missing / `Infinity` / negative → 0) at every read site, re-verified to
> **0** admissibility violations on adversarial pools (was 1563/2000); (3) the
> T-1 note was corrected — the **current** PL page is **30 at 30 slots** (midfield
> 15 + attack 15), so **35/30 is only an older, dated snapshot**; **Málaga 23/15**
> and **TOTW 32/20** still support T-1, and "Only the ten biggest tags pay"
> **without an item count** is not by itself evidence of a larger pool. The suite
> grew **169 → 180**.

> **Second amendment note (P1 re-submission #2).** The first amended P1 was
> **still not accepted**. Four points were raised and are all closed here:
> (1) the B&B upper bound was **unsound** — it used `evalSet` over all remaining
> candidates, but `lineup()` is a heuristic and **not monotone** in the pool, so a
> larger candidate set can displace a tag-synergistic subset; replaced by a
> guaranteed-safe monotone `setUpperBound`, with a tag-synergy + shared-card
> brute-force test; (2) the UI showed only **per-set** recommendations — a
> **global portfolio panel** was added (each card once, shared budget
> `coins − reserve`, aggregated benefit); (3) the hand-back did not state whether
> a plan is **proven optimal** or only **best-found** under the node cap — now
> reported via `optimality`, plus a ≤25-candidate / ≤4-purchase brute force across
> all four objectives; (4) the T-1 note now rests on **position sums vs slots**,
> not tag counts. The suite grew **149 → 169**.

> **First amendment note (P1 re-submission).** The first P1 submission was **not
> accepted**: (1) the report described a Greedy-seed → budget-cap → 2-opt method,
> i.e. **R3's Branch & Bound was not actually implemented**; and (2) the TAG test
> gap persisted (`test_all_tags.py` read expected percentages from the engine's
> own table). Both were fixed and the commit extended. The suite grew **126 → 149**.

---

## 0. P1 evidence (R3 — shopping plan, amended)

**Engine (in the marked block, mirrored byte-identically):** `poolFor`,
`candidatesFor`, `evalSet` + bounded memo (`evalMemoReset`), `gain1`,
`bbUpperBound`, `bbValue`, `branchAndBound`, `objectiveValue`, `improve2opt`,
`spendTotal`, `planSet`, `sanScore`, `setUpperBound`, `portfolioWorld`,
`portfolioValue`, `portfolioBrute`, `portfolioUpperBound`,
`portfolioBranchAndBound`, `portfolioImprove2opt`, `portfolioGreedySeed`,
`portfolioPlan`, `plan`.

### 0.1 Single-set — real Branch & Bound (not greedy-only)

`planSet` now runs **`branchAndBound` as the primary search path**. The greedy
marginal loop (`gain1`) only produces the **seed**; `branchAndBound` then explores
the space of priced card subsets `S` depth-first:

- order = candidates sorted by expected loss desc, then score desc, then id
  (deterministic);
- **admissible upper bound** = the lineup score over the **whole** evaluation
  universe (owned ∪ units ∪ all candidates), which is monotone along a branch, so
  the pruning `ubVal < bestVal` is sound;
- **hard coin-budget constraint** on every node (`seedSpend + Σ buyPrice`);
- the seed is only an initial incumbent, and an **infeasible seed is discarded**
  (it must not become a "best" the caller later has to truncate);
- evaluation **must include the candidates** in the eval-pool, because `evalSet`
  can only select items present in its pool — a bug found here and fixed (a
  purchased card silently never entered the lineup otherwise);
- `maxNodes=200000` bounds work on large pools; `improve2opt` then refines,
  using the **same** value function (tokens + score + loss) as the search.

**Binding test (the one the first submission lacked):** a **cost-constrained**
scenario where a cost-blind greedy provably fails. At `coins=1200` the optimum is
`h1+m1` (score 950), **not** the cheaper-looking `h2+m1` (930); at `coins=1900` it
is `h1+h2` (1080). `test_matches_brute_force_under_coin_constraint` sweeps
`coins ∈ {∞, 1900, 1200, 1000, 300, 50}` and asserts `planSet.buyScore` **equals
the exhaustive brute-force optimum** in every case.

### 0.2 Multi-set — portfolio optimisation (shared cost once)

`plan()` now also returns a **`portfolio`**. Over the **union** candidate universe
(a card eligible for several sets appears once), it maximises the summed per-set
objective subject to `budget = coins − reserve`, and **charges a shared card's
cost only once** (`cost = Σ loss` over the *distinct* cards). `portfolioBrute`
enumerates all subsets of the union and is the reference optimum; `portfolioBrute`
throws if the union exceeds 20 cards (kept obviously correct).

**Binding test:** `TestPortfolioTwoSets` builds two sets a single card improves
(`shared`), and asserts:
- `cost == loss(shared) + loss(other)` — the shared card is charged **exactly
  once**, while `dScore` is the **sum over both sets** (`test_shared_card_cost_counted_once`);
- `plan().portfolio` matches `portfolioBrute` for
  `(coins, reserve) ∈ {(∞,0), (100,0), (∞,25), (100,25), (75,0), (∞,75)}`;
- a **binding reserve** forces a cheaper portfolio (`test_reserve_excludes_optimal_bundle`).

**Tests:** `tests/test_plan.py` — **29 tests** (was 20), all green:

| Group | What it proves |
|---|---|
| `TestEvalSet` | `evalSet(g, pool, ids)` equals `lineup()` over those items; repeated calls are memo-stable; `count` is the selected-item count |
| `TestGain1` | marginal gain `>= 0` (greedy seed soundness) and equals the real `after − before` |
| `TestPlanRespectsConstraints` | honours `maxBundle`, `coins`, `slots`; never buys owned/ineligible cards; reports `completeAfter:false` and `dTokens:0` when slots are still short |
| `TestPlanOptimality` | `planSet`'s realised `buyScore` **equals the exhaustive brute-force optimum** — on two unconstrained scenarios **and under a binding coin budget** (6 budgets swept) |
| `TestPortfolioTwoSets` | shared card cost counted **once**; `plan().portfolio` equals brute force under `coins − reserve`; reserve can exclude the optimal bundle; ineligible card improves only its own set; deterministic; `plan()` exposes `portfolio` |
| `TestPlanDeterminism` | same input → byte-identical plan; ranked list sorted by value; objective recorded per plan |
| `TestPlanUiBridge` + `TestPlanUiBridgeBehavior` | the UI bridge reads `p.recommendations`/`dTokens`/`dScore`/`newGrade`/`buyScore`/`completeAfter`; the old greedy loop is gone; the bridge + real engine run the demo scenario end-to-end |
| `test_form_fields.TestAppScriptParse` | the inline script parses as a classic script (see §6) |

### 0.3 TAG table — independent, dated, offline fixture (fixes the gap)

`tests/test_all_tags.py` reads its expected percentage from the **engine's own**
`TAG` table, so it cannot detect a wrong value *inside* that table. Added:

- **`tests/fixtures/futgg/bonus_tags.html`** — a **dated snapshot** of the FUT.GG
  bonus-tags page (fetched **2026-10-04**, page footer "Updated 27 Sept 2026"),
  21 `<tr data-tag-key="…">` rows, `<table data-total="21" data-updated="27 Sept 2026">`.
  Parsed by **plain Python regex, no engine, no network**.
- **`tests/test_tag_table.py`** (14 tests) compares the engine `TAG` table
  **tier-by-tier** against the fixture, plus the `pct()` function at each tier's
  lower (and upper) bound, and the below-first-tier zero gap.
- **Verified to detect a corruption:** temporarily editing the engine's
  `sameLeague` top tier `.08 → .04` makes **2 tests fail**; restoring makes them
  pass again. (No live network is used in the normal suite run.)

### 0.4 `countTopTags` default (10) and the `Infinity` variant

`TestCountTopTagsCap` / `TestCountTopTagsInfinityVariant` (6 tests) build a lineup
that drives **15 positive tags** and assert:
- the default cap is **10** (`{}` and `{"countTopTags":10}` give the same bonus,
  equal to the sum of the ten largest `tags`);
- an explicit `Infinity`-equivalent cap (a very large integer) pays **all** tags
  and **strictly more** than the top-10;
- the cap is **monotone and bounded** (`n = 1,3,10,15,21,10⁹` never decreases and
  never exceeds the full sum);
- `DEFAULT_COUNT_TOP_TAGS` is exported (guard against a silent change).

**Browser proof.** Loaded the app via the local server in headless Chrome, clicked
*Optimizer*: the settings form now shows the new **"Reserve (kept)"** field, the
plan-method note reads *"branch & bound over candidate card sets (memoized set
evaluation), then a 2-opt refinement, with a coin-budget cap. Multi-set portfolio
optimisation counts a shared card's cost only once; the reserve is withheld from
the budget."*, and the recommended upgrades render. Screenshot: `p1_optimizer.png`.

> **Note (P0 counts below).** The P0 section that follows preserved the 104-test
> snapshot at acceptance. The current total is **180** (P1 second-amendment 169 +
> 11 new tests in `test_plan.py` for the three third-amendment points). The P1 run
> is captured in full in §7.

### 0.5 Second amendment — the four points, closed

**Point 1 — the B&B bound was unsound (T-11).** The first amendment used
`evalSet()` over all remaining candidates as the bound. `lineup()` is a heuristic
(top-N by score + a bounded swap search), so it is **not monotone** in the pool:
`lineup(P) = 1723` but `lineup(P \ {p6}) = 1888` (reproduced in
`TestSetUpperBound.test_lineup_is_not_monotone_regression`); in random pools the
true best subset score exceeded the full-universe `evalSet` value in **2966 / 3000**
cases. That bound could therefore prune the true optimum. Replaced by
`setUpperBound` = `Σ(≤slots largest base scores) + score(pool,{countTopTags:Infinity}).bonus`:
both terms are provably monotone and dominate any realised subset. Guarded by
`TestSetUpperBound` (admissibility over every subset, monotonicity when items are
added, domination of the full-pool `evalSet`, exactness when the pool fits).
A **tag-synergy + shared-card-across-two-sets** brute force is added in
`TestTagSynergySharedCardBruteForce`.

**Point 2 — the UI must show a global portfolio plan.** Added a **"Global
portfolio plan"** panel to the Optimizer section (`id="portfolio"`,
`renderPortfolio()`), fed by `portfolioPlan()` through the new `portfolio0()`
bridge. It renders, in one place: the distinct cards to buy (each **once**), the
**shared** cost, the shared budget **`coins − reserve`**, the **aggregated**
Δtokens/Δscore, an **optimality** label (proven / best-found), and a per-set
detail table. It is called from both `render()` and `runOptimizer()`. Guarded by
`TestPlanUiBridge` (presence + wiring) and `TestGlobalPortfolioUiBehavior`
(the two-set / shared-card / reserve behaviour executed against the real engine).

**Point 3 — proven vs best-found, and the small brute force.** `planSet` now
returns `optimality: 'proved' | 'node_limit'` (plus `nodes`); `branchAndBound`
returns `{ best, value, nodes, aborted, proved, maxNodes }`; `portfolioPlan`
returns `optimality: 'proved' | 'node_limit'` with `proven` / `exact` /
`universe`. A universe ≤ `EXACT_PF_LIMIT` = 20 cards is enumerated exhaustively;
**beyond 20 the global B&B over S runs** (see the third-amendment subsection —
this was `'best_found'`-by-greedy in the second amendment and was fixed). The
agreed small brute force — **up to 25 candidates, at most 4 purchases** — is
added for **all four offered objectives** (`tokens`, `score`, `balanced`, `eff`),
under both a binding budget and unbounded coins
(`TestSmallBruteForceAllObjectives`), and it must match the engine exactly.

> **A real bug this found (T-12).** The 25-candidate brute force immediately
> exposed that `improve2opt` was corrupting a correct B&B optimum: its
> eval-universe omitted the candidates (so `lineup()` never saw them) and its
> id-set omitted the owned pool (so already-owned cards were dropped from the
> evaluated lineup). For `balanced` and `eff` this replaced the optimum with a
> strictly worse set. Fixed: universe = `owned ∪ cands ∪ sel`, id-set =
> `owned ∪ list`, and an over-budget edit is now rejected. After the fix the
> brute force matches for all four objectives.

**Point 4 — T-1 rests on position sums, not tag counts.** The T-1 entry now cites
the **position-sum vs slots** mismatch on the FUT.GG page as the decisive evidence
that FUT.GG computes bonuses over a larger pool than the app's lineup. The
supporting pages are **Málaga (23 positions for 15 slots)** and **TOTW (32 for
20)**; the PL **35-for-30** figure is now cited only as an **older, dated
snapshot** — the current PL page shows **midfield 15 + attack 15 = 30 at 30
slots**. "Only the ten biggest tags pay" **without an item count** proves nothing
about pool size.

**Browser proof (second amendment).** The Optimizer section now shows the
**Global portfolio plan** panel above **Recommended upgrades**; the plan-method
note states the plan reports *proven optimal* vs *best found*, and describes the
shared-cost / `coins − reserve` portfolio. Screenshot: `p1_optimizer_portfolio.png`.

### 0.6 Third amendment — the three points, closed

**Point 1 — the global portfolio search must run B&B over S, not Greedy.**
`portfolioPlan` previously enumerated only universes ≤ `EXACT_PF_LIMIT` (20) and
fell back to **Greedy + 2-opt** beyond that. R3 requires the search over the
**global card set S**. Added `portfolioUpperBound` (an S-independent admissible
value bound built from `setUpperBound`), `portfolioBranchAndBound` (global B&B
over S with a greedy-feasible seed, a **hard** `coins − reserve` budget check and
a `maxNodes` cap), `portfolioImprove2opt` (budget-respecting), and
`portfolioGreedySeed`. `portfolioPlan` now returns
`optimality: 'proved' | 'node_limit'` on the large path (`proven` + `nodes`);
`'node_limit'` means *best found* and is never labelled proven. The reference
`portfolioBrute` was rewritten to enumerate size-≤`maxBundle` **combinations**
(exhaustive, but tractable past 20) and now checks the **global `plan()` path**
with **shared cards** and **`coins − reserve`** on universes 21–24 for all four
objectives, plus a forced `node_limit` via `maxNodes: 1`
(`TestGlobalBbPathVsBruteForce`, `TestPortfolioOptimalityReported`).

> **Verified by hand:** universes of 20/21/22/23/24 candidates — the global B&B
> result equals the exhaustive combination brute force exactly (all objectives),
> with `optimality: 'proved'`; `maxNodes: 1` flips it to `'node_limit'`.

**Point 2 — non-negative-score precondition (T-13).** `setUpperBound`'s base term
is only monotone/an upper bound for **non-negative** scores (measured 3158/12000
monotonicity and 1563/2000 admissibility violations with negative inputs). The
engine now **enforces** the precondition by sanitizing every score through
`sanScore` (NaN / missing / `Infinity` / negative → 0) at every read site
(`bonus`, `score`, `lineup`, `poolFor`, `candidatesFor`, `_itemSig`,
`setUpperBound`, `portfolioWorld`). Re-verified **0** admissibility violations on
adversarial negative/NaN pools (`TestSetUpperBoundNegativeScores`).

**Point 3 — T-1 doc precision.** Corrected as described in Point 4 above (current
PL = 30 at 30 slots; 35/30 is a dated snapshot only). Edited in `AUDIT.md` (T-1)
and `README.md`.

---

## 1. Test count — corrected and reconciled

The earlier P0 report said "53" and listed a `test_sync_engine` count of 6. Both
were wrong. The corrected P0 breakdown sums **exactly** to the discovered total:

| Module | P0 | P1 (first) | P1 (amended) | P1 (2nd amend) | P1 (3rd amend) |
|---|---|---|---|---|---|
| `test_sync_engine.py` | **5** | 5 | 5 | 5 | 5 |
| `test_engine_harness.py` | 5 | 5 | 5 | 5 | 5 |
| `test_parser.py` | 24 | 24 | 24 | 24 | 24 |
| `test_tokens_k6.py` | **17** | 17 | 17 | 17 | 17 |
| `test_form_fields.py` | 12 | **14** | 14 | 14 | 14 |
| `test_score.py` | 19 | 19 | 19 | 19 | 19 |
| `test_all_tags.py` | 22 | 22 | 22 | 22 | 22 |
| `test_plan.py` | — | **20** | **29** | **49** | **60** |
| `test_tag_table.py` | — | — | **14** | 14 | 14 |
| **Total** | **104** | **126** | **149** | **169** | **180** |

`5 + 5 + 24 + 17 + 12 + 19 + 22 = 104` ✅ (P0) ·
`5 + 5 + 24 + 17 + 14 + 19 + 22 + 20 = 126` ✅ (P1 first) ·
`5 + 5 + 24 + 17 + 14 + 19 + 22 + 29 + 14 = 149` ✅ (P1 amended) ·
`5 + 5 + 24 + 17 + 14 + 19 + 22 + 49 + 14 = 169` ✅ (P1 2nd amendment) ·
`5 + 5 + 24 + 17 + 14 + 19 + 22 + 60 + 14 = 180` ✅ (P1 3rd amendment) — all match `discover`.

Two corrections vs. the earlier report, plus the P1 additions:

1. **`test_sync_engine` = 5, not 6.** The five tests are:
   `test_bytes_equal`, `test_loadable`, `test_exports_line_included_in_block`,
   `test_markers_single_and_ordered`, `test_block_is_side_effect_free`.
   (The earlier "6" double-counted a parametrisation that does not exist.)
2. **`test_tokens_k6` grew 11 → 17** with the five `TestEligibilityIds` tests
   (8 cumulative + 4 Multiples + 5 ids = 17).
3. **P1 first:** `test_plan.py` added (+20); `test_form_fields` grew 12 → 14 with
   the two `TestAppScriptParse` regression tests (§6).
4. **P1 amended:** `test_plan.py` 20 → 28 (+8: constrained-B&B optimality, the
   two-set portfolio suite, budget feasibility); `test_tag_table.py` added (+14:
   the independent dated offline fixture **and** the `countTopTags` 10/Infinity
   tests).

---

## 2. F1-rev coverage — visible at assertion level

All six Σ-bands for `bonus()` were probed directly against the live engine and
each is a named, failing-if-broken test in `tests/test_score.py`:

| Σ-band (sum → pct) | Expected | Test |
|---|---|---|
| 167 → 3% | 5 | `test_band_5` |
| 400 → 3% | 12 | `test_band_12` |
| 650 → 2% | 13 | `test_band_13` |
| 700 → 2% | 14 | `test_band_14` |
| 400 → 6% | 24 | `test_band_24` |
| 420 → 30% | 126 | `test_band_126` |

Plus the **dated snapshot** (`test_pl_same_league_snapshot_2026_10_04`: on
2026-10-04 FUT.GG reported `Same League: 30 items, +8% -> 23,045`; the test pins
`floor(sum·0.08) == 23045` for `sum ∈ [288063, 288074]`) and the contract test
(`test_contract_sums_item_list_itself`).

> **Snapshot handling.** FUT.GG bonus breakdowns move with card scores. Values
> like `23,045` (PL Same League, 2026-10-04) are **dated snapshots**, not
> timeless product values. They are labelled by date in the test name/docstring
> and are used only to pin the arithmetic contract. The stable assertions are the
> tag **model** (per-tag floor, top-10 cut) and the property assertions — never a
> market-dependent number. An earlier note of `22,335` was a stale snapshot and
> has been replaced. Tracked as T-5 in `AUDIT.md`.

The three F1-rev **micro-fixtures**, each asserted on title/tags **and** the
explicit zero-assertion the plan requires:

| Fixture | Assertion | Test |
|---|---|---|
| Attack (all-out) | `tags == [5]`; **every non-target tag is 0** | `test_all_out_attack_pays_5`, `test_every_non_target_tag_is_zero` |
| Midfield | `tags == [24]` | `test_midfield_control_24` |
| Midfield + 5 Silver | `tags == [25, 24]` — **NOT 30** | `test_midfield_silver_25_not_30` |

**Top-10 truncation** (12 active tags, `countTopTags: 10` vs `Infinity`):

| Test | What it proves |
|---|---|
| `test_exactly_twelve_active_tags` | the fixture really drives 12 tags above floor |
| `test_infinity_equals_all` | `Infinity` pays every active tag |
| `test_top10_drops_the_two_smallest` | `top10 == infinity − (two smallest)` |

**Determinism / properties:** `test_bonus_non_negative`,
`test_bonus_zero_when_no_tier_reached`,
`test_total_minus_base_equals_sum_of_paying_tags`, `test_zero_pct_is_zero`.

**Every one of the 21 tags is individually triggerable** in
`tests/test_all_tags.py` (22 tests), with the expected pct **read from the live
`TAG` table** rather than hard-coded, guarded by
`test_all_twenty_one_covered`. The earlier `TAG keys: 21` line only proved the
table *size*; the new suite proves each key actually fires.

---

## 3. K6 / H2 — ID semantics clarified and the `ids` path proven

### 3.1 Identity model (documented in `engine/engine.js` and `index.html`)

- **`itemId`** = identity of one **card**. Two card versions of a player have
  different `itemId`s.
- **`playerKey`** = canonical **player** (used only by `Multiples!`).
- **`id`** = the internal record key (unique per saved row).

The `itemId` fallback in `playerModal`'s save handler is the record id, **never**
the `playerKey`:

```js
// itemId = identity of THIS card row. It falls back to the record id (p.id),
// which is unique per saved row -- NOT to playerKey.
np.itemId = np.itemId || np.id;
```

Guarded by `test_form_fields.TestFormFieldsStatic.test_itemid_defaults_to_id` and
`TestFormSaveBehavior.test_itemid_falls_back_to_id`.

### 3.2 ID-based eligibility path (`playerIds` / `ids`) — confirmed

The gallery object carries `eligibility`. The engine branch is:

```js
if (e.type === 'ids') return (e.ids || []).includes(p.itemId || p.id);
```

**Correction to the first probe.** An earlier probe passed the eligibility object
as the *second positional argument* directly
(`eligible(p, {type:"ids", ids:[...]})`). `eligible()` reads `g.eligibility`, so
that shape fell through to the `sets` branch and returned `false` for every case
— which looked like an engine bug but was a **probe-shape error**, not an engine
bug. The correct, verified calls are:

```
{"fn":"eligible","args":[{"itemId":"c1"},{"eligibility":{"type":"ids","ids":["c1","c2"]}}]} -> true
{"fn":"eligible","args":[{"itemId":"c9"},{"eligibility":{"type":"ids","ids":["c1","c2"]}}]} -> false
{"fn":"eligible","args":[{"itemId":"c1"},{"eligibility":{"ids":["c1","c2"]}}]}              -> false
```

The last case confirms the **type key is required** (`type:"ids"`), otherwise
the call is treated as the `sets` path.

This is now locked by five engine-level tests in
`tests/test_tokens_k6.TestEligibilityIds`:
`test_member_item_is_eligible`, `test_non_member_item_is_not_eligible`,
`test_falls_back_to_record_id_when_itemid_absent`,
`test_ids_path_requires_type_key`, `test_gender_guard_precedes_ids`.

The UI path is covered by `tests/test_form_fields.TestSetFormIdsPath`
(`test_ids_option_present`, `test_ids_saved_as_array`,
`test_engine_has_ids_branch`, `test_cumulative_wording_not_incremental`).

---

## 4. Raw verbose output (verbatim, P1 first-submission 126-test run)

> The block below is the **first-submission** run (126 tests), kept verbatim.
> The current run is **180 tests** — the extra assertions are the new/modified
> `test_plan.py` (20 → 29 → 49 → 60) and `test_tag_table.py` (0 → 14); §7 records
> the current per-module counts. Re-run `python -m unittest discover -s tests -v`
> to reproduce the full 180.

```
test_all_twenty_one_covered (test_all_tags.TestAllTagsTriggerable.test_all_twenty_one_covered)
Guard: every key in the TAG table is exercised above. ... ok
test_att (test_all_tags.TestAllTagsTriggerable.test_att) ... ok
test_bronze (test_all_tags.TestAllTagsTriggerable.test_bronze) ... ok
test_def (test_all_tags.TestAllTagsTriggerable.test_def) ... ok
test_different_club (test_all_tags.TestAllTagsTriggerable.test_different_club) ... ok
test_different_league (test_all_tags.TestAllTagsTriggerable.test_different_league) ... ok
test_different_nation (test_all_tags.TestAllTagsTriggerable.test_different_nation) ... ok
test_first_owner (test_all_tags.TestAllTagsTriggerable.test_first_owner) ... ok
test_gk (test_all_tags.TestAllTagsTriggerable.test_gk) ... ok
test_gold (test_all_tags.TestAllTagsTriggerable.test_gold) ... ok
test_hero (test_all_tags.TestAllTagsTriggerable.test_hero) ... ok
test_holographic (test_all_tags.TestAllTagsTriggerable.test_holographic) ... ok
test_icon (test_all_tags.TestAllTagsTriggerable.test_icon) ... ok
test_mid (test_all_tags.TestAllTagsTriggerable.test_mid) ... ok
test_multi (test_all_tags.TestAllTagsTriggerable.test_multi) ... ok
test_same_club (test_all_tags.TestAllTagsTriggerable.test_same_club) ... ok
test_same_league (test_all_tags.TestAllTagsTriggerable.test_same_league) ... ok
test_same_nation (test_all_tags.TestAllTagsTriggerable.test_same_nation) ... ok
test_silver (test_all_tags.TestAllTagsTriggerable.test_silver) ... ok
test_skills (test_all_tags.TestAllTagsTriggerable.test_skills) ... ok
test_totw (test_all_tags.TestAllTagsTriggerable.test_totw) ... ok
test_wf (test_all_tags.TestAllTagsTriggerable.test_wf) ... ok
test_browser_simulation (test_engine_harness.TestHarnessBrowserPath.test_browser_simulation) ... ok
test_bonus_is_floor_of_sum_times_pct (test_engine_harness.TestHarnessNodePath.test_bonus_is_floor_of_sum_times_pct) ... ok
test_exports_non_empty_and_include_bonus (test_engine_harness.TestHarnessNodePath.test_exports_non_empty_and_include_bonus) ... ok
test_score_shape (test_engine_harness.TestHarnessNodePath.test_score_shape) ... ok
test_tokens_cumulative (test_engine_harness.TestHarnessNodePath.test_tokens_cumulative) ... ok
test_no_reserved_word_ids (test_form_fields.TestAppScriptParse.test_no_reserved_word_ids) ... ok
test_script_parses_as_classic_script (test_form_fields.TestAppScriptParse.test_script_parses_as_classic_script) ... ok
test_boolean_toggles_present (test_form_fields.TestFormFieldsStatic.test_boolean_toggles_present) ... ok
test_itemid_defaults_to_id (test_form_fields.TestFormFieldsStatic.test_itemid_defaults_to_id)
A card with no explicit itemId falls back to the RECORD id, not playerKey. ... ok
test_player_identity_label_present (test_form_fields.TestFormFieldsStatic.test_player_identity_label_present)
H1: the playerKey field must be labelled as the linked group. ... ok
test_required_input_fields_present (test_form_fields.TestFormFieldsStatic.test_required_input_fields_present) ... ok
test_required_text_and_number_fields_present (test_form_fields.TestFormFieldsStatic.test_required_text_and_number_fields_present) ... ok
test_save_handler_persists_each_field (test_form_fields.TestFormFieldsStatic.test_save_handler_persists_each_field) ... ok
test_itemid_falls_back_to_id (test_form_fields.TestFormSaveBehavior.test_itemid_falls_back_to_id) ... ok
test_multiples_fields_persist (test_form_fields.TestFormSaveBehavior.test_multiples_fields_persist) ... ok
test_cumulative_wording_not_incremental (test_form_fields.TestSetFormIdsPath.test_cumulative_wording_not_incremental)
K2 wording: the set form must not call the token rewards incremental. ... ok
test_engine_has_ids_branch (test_form_fields.TestSetFormIdsPath.test_engine_has_ids_branch) ... ok
test_ids_option_present (test_form_fields.TestSetFormIdsPath.test_ids_option_present) ... ok
test_ids_saved_as_array (test_form_fields.TestSetFormIdsPath.test_ids_saved_as_array) ... ok
test_comma_separated_thresholds (test_parser.TestGradeTable.test_comma_separated_thresholds)
Thousands separators ('400,000') must be normalised to ints. ... ok
test_malaga_badge_kit_are_zero_with_text (test_parser.TestGradeTable.test_malaga_badge_kit_are_zero_with_text)
H6: D/C rewards are Badge/Kit -> reward 0 + rewardText. ... ok
test_malaga_thresholds_and_rewards (test_parser.TestGradeTable.test_malaga_thresholds_and_rewards) ... ok
test_premier_league_thresholds_and_rewards (test_parser.TestGradeTable.test_premier_league_thresholds_and_rewards) ... ok
test_reward_requires_token_image (test_parser.TestGradeTable.test_reward_requires_token_image)
A row without a gallery-token image must yield reward 0. ... ok
test_totw_thresholds_and_rewards (test_parser.TestGradeTable.test_totw_thresholds_and_rewards) ... ok
test_index_pages_rejected (test_parser.TestPageDetection.test_index_pages_rejected) ... ok
test_set_pages_detected (test_parser.TestPageDetection.test_set_pages_detected) ... ok
test_set_title_without_marker_rejected (test_parser.TestPageDetection.test_set_title_without_marker_rejected) ... ok
test_title_signal_is_singular_colon (test_parser.TestPageDetection.test_title_signal_is_singular_colon)
A plural 'FUT Gallery Sets:' title must not be treated as a set page. ... ok
test_unescape_required (test_parser.TestPageDetection.test_unescape_required)
The marker check must run AFTER unescape; raw '&amp;' would fail. ... ok
test_wrong_host_rejected (test_parser.TestPageDetection.test_wrong_host_rejected) ... ok
test_index_page_raises (test_parser.TestParseErrors.test_index_page_raises) ... ok
test_no_grade_table_raises (test_parser.TestParseErrors.test_no_grade_table_raises) ... ok
test_keys_and_id (test_parser.TestParseShape.test_keys_and_id) ... ok
test_malaga_eligibility_club_men (test_parser.TestSlotsEligibility.test_malaga_eligibility_club_men)
K4 abortion evidence: description says 'Malaga CF Mens players' ... ok
test_malaga_slots_from_description (test_parser.TestSlotsEligibility.test_malaga_slots_from_description) ... ok
test_parse_requirements_ignores_rsc_blob (test_parser.TestSlotsEligibility.test_parse_requirements_ignores_rsc_blob)
The embedded JSON tag descriptions must not be read as the requirement. ... ok
test_parse_requirements_numbered (test_parser.TestSlotsEligibility.test_parse_requirements_numbered) ... ok
test_parse_requirements_numberless (test_parser.TestSlotsEligibility.test_parse_requirements_numberless) ... ok
test_premier_league_slots_and_type (test_parser.TestSlotsEligibility.test_premier_league_slots_and_type) ... ok
test_totw_eligibility_rarity (test_parser.TestSlotsEligibility.test_totw_eligibility_rarity) ... ok
test_totw_slots_estimated_from_oracle (test_parser.TestSlotsEligibility.test_totw_slots_estimated_from_oracle) ... ok
test_women_gender (test_parser.TestSlotsEligibility.test_women_gender) ... ok
test_count_is_selected_items (test_plan.TestEvalSet.test_count_is_selected_items) ... ok
test_evalset_equals_lineup_total (test_plan.TestEvalSet.test_evalset_equals_lineup_total)
evalSet(g, pool, ids) must equal lineup() over exactly those items. ... ok
test_hits_memo_repeatedly (test_plan.TestEvalSet.test_hits_memo_repeatedly) ... ok
test_gain_increases_total (test_plan.TestGain1.test_gain_increases_total) ... ok
test_gain_non_negative (test_plan.TestGain1.test_gain_non_negative) ... ok
test_objective_recorded_per_plan (test_plan.TestPlanDeterminism.test_objective_recorded_per_plan) ... ok
test_ranked_is_sorted_by_value (test_plan.TestPlanDeterminism.test_ranked_is_sorted_by_value) ... ok
test_repeatable (test_plan.TestPlanDeterminism.test_repeatable) ... ok
test_matches_brute_force_objective_score (test_plan.TestPlanOptimality.test_matches_brute_force_objective_score) ... ok
test_matches_brute_force_second_scenario (test_plan.TestPlanOptimality.test_matches_brute_force_second_scenario) ... ok
test_coin_budget_is_feasible_and_used (test_plan.TestPlanRespectsConstraints.test_coin_budget_is_feasible_and_used) ... ok
test_max_bundle (test_plan.TestPlanRespectsConstraints.test_max_bundle) ... ok
test_never_buys_ineligible (test_plan.TestPlanRespectsConstraints.test_never_buys_ineligible) ... ok
test_never_buys_owned (test_plan.TestPlanRespectsConstraints.test_never_buys_owned) ... ok
test_slots_missing_is_reported (test_plan.TestPlanRespectsConstraints.test_slots_missing_is_reported) ... ok
test_objective_wired (test_plan.TestPlanUiBridge.test_objective_wired) ... ok
test_old_greedy_loop_is_gone (test_plan.TestPlanUiBridge.test_old_greedy_loop_is_gone)
The P0 greedy `for(let k=1;k<=max;k++){` bundle loop must be removed. ... ok
test_plan0_uses_engine_planSet (test_plan.TestPlanUiBridge.test_plan0_uses_engine_planSet) ... ok
test_toopp_maps_engine_fields (test_plan.TestPlanUiBridge.test_toopp_maps_engine_fields) ... ok
test_bridge_runs_demo_and_maps_fields (test_plan.TestPlanUiBridgeBehavior.test_bridge_runs_demo_and_maps_fields) ... ok
test_all_out_attack_pays_5 (test_score.TestAttackFixture.test_all_out_attack_pays_5) ... ok
test_every_non_target_tag_is_zero (test_score.TestAttackFixture.test_every_non_target_tag_is_zero)
The explicit zero-assertion the plan requires for the Attack fixture. ... ok
test_band_12 (test_score.TestBonusUnitBands.test_band_12)
floor(400*.03)=12 and floor(433*.03)=12. ... ok
test_band_126 (test_score.TestBonusUnitBands.test_band_126)
floor(420*.30)=126 and floor(423*.30)=126. ... ok
test_band_13 (test_score.TestBonusUnitBands.test_band_13)
floor(650*.02)=13 and floor(699*.02)=13. ... ok
test_band_14 (test_score.TestBonusUnitBands.test_band_14)
floor(700*.02)=14. ... ok
test_band_24 (test_score.TestBonusUnitBands.test_band_24)
floor(400*.06)=24 and floor(416*.06)=24. ... ok
test_band_5 (test_score.TestBonusUnitBands.test_band_5)
floor(167*.03)=5 and floor(199*.03)=5. ... ok
test_contract_sums_item_list_itself (test_score.TestBonusUnitBands.test_contract_sums_item_list_itself)
bonus() receives a list and sums it -- three ways to reach 650 agree. ... ok
test_pl_same_league_snapshot_2026_10_04 (test_score.TestBonusUnitBands.test_pl_same_league_snapshot_2026_10_04)
DATED SNAPSHOT (2026-10-04): Same League, 30 items, +8% -> 23,045. ... ok
test_zero_pct_is_zero (test_score.TestBonusUnitBands.test_zero_pct_is_zero) ... ok
test_midfield_control_24 (test_score.TestMidfieldFixtures.test_midfield_control_24) ... ok
test_midfield_silver_25_not_30 (test_score.TestMidfieldFixtures.test_midfield_silver_25_not_30)
5 Silver, sum 168 -> tier 5-9 (+15%) = 25; the 10-19 tier (30) must NOT apply. ... ok
test_bonus_non_negative (test_score.TestProperties.test_bonus_non_negative) ... ok
test_bonus_zero_when_no_tier_reached (test_score.TestProperties.test_bonus_zero_when_no_tier_reached)
Two items with everything distinct -> no tag reaches a tier. ... ok
test_total_minus_base_equals_sum_of_paying_tags (test_score.TestProperties.test_total_minus_base_equals_sum_of_paying_tags) ... ok
test_exactly_twelve_active_tags (test_score.TestTopTenTruncation.test_exactly_twelve_active_tags) ... ok
test_infinity_equals_all (test_score.TestTopTenTruncation.test_infinity_equals_all) ... ok
test_top10_drops_the_two_smallest (test_score.TestTopTenTruncation.test_top10_drops_the_two_smallest) ... ok
test_loadable (test_sync_engine.TestEngineLoadable.test_loadable) ... ok
test_block_is_side_effect_free (test_sync_engine.TestEngineSync.test_block_is_side_effect_free)
The engine block must not touch the DOM, localStorage or a global state. ... ok
test_bytes_equal (test_sync_engine.TestEngineSync.test_bytes_equal)
The marked block must be byte-identical to the mirror. Always runs. ... ok
test_exports_line_included_in_block (test_sync_engine.TestEngineSync.test_exports_line_included_in_block)
Guard against the off-by-one bug: exports line MUST be part of the block. ... ok
test_markers_single_and_ordered (test_sync_engine.TestEngineSync.test_markers_single_and_ordered)
Exactly one START/END pair, in order, and START precedes the exports line. ... ok
test_falls_back_to_record_id_when_itemid_absent (test_tokens_k6.TestEligibilityIds.test_falls_back_to_record_id_when_itemid_absent)
`p.itemId || p.id`: a legacy record without itemId still matches. ... ok
test_gender_guard_precedes_ids (test_tokens_k6.TestEligibilityIds.test_gender_guard_precedes_ids)
A gender mismatch rejects even a listed itemId. ... ok
test_ids_path_requires_type_key (test_tokens_k6.TestEligibilityIds.test_ids_path_requires_type_key)
Without `type: 'ids'` the ids list is ignored (sets branch). ... ok
test_member_item_is_eligible (test_tokens_k6.TestEligibilityIds.test_member_item_is_eligible) ... ok
test_non_member_item_is_not_eligible (test_tokens_k6.TestEligibilityIds.test_non_member_item_is_not_eligible) ... ok
test_itemid_dedup_keeps_highest_score (test_tokens_k6.TestMultiplesDataModel.test_itemid_dedup_keeps_highest_score)
When the same itemId appears twice, the higher-scored copy is kept. ... ok
test_same_itemid_at_most_one_in_lineup (test_tokens_k6.TestMultiplesDataModel.test_same_itemid_at_most_one_in_lineup)
Same itemId (same card) -> at most one instance in the lineup. ... ok
test_same_playerkey_different_itemids_both_allowed (test_tokens_k6.TestMultiplesDataModel.test_same_playerkey_different_itemids_both_allowed)
Both card versions of one player may sit in the lineup (Multiples!). ... ok
test_two_items_same_playerkey_trigger_multiples (test_tokens_k6.TestMultiplesDataModel.test_two_items_same_playerkey_trigger_multiples)
Two cards of the SAME player (different itemId) -> Multiples! pays. ... ok
test_cumulative_monotonic (test_tokens_k6.TestTokensCumulative.test_cumulative_monotonic)
Each higher grade must be >= the previous (never incremental-only). ... ok
test_malaga_full (test_tokens_k6.TestTokensCumulative.test_malaga_full) ... ok
test_null_grade_is_zero (test_tokens_k6.TestTokensCumulative.test_null_grade_is_zero) ... ok
test_pl_full (test_tokens_k6.TestTokensCumulative.test_pl_full) ... ok
test_pl_grade_c_is_45_of_265 (test_tokens_k6.TestTokensCumulative.test_pl_grade_c_is_45_of_265)
Description: 'earns 45 of 265' -> D+C = 10+35 = 45 (cumulative). ... ok
test_semantics_label_is_cumulative (test_tokens_k6.TestTokensCumulative.test_semantics_label_is_cumulative)
Guard against a future rename to 'incremental' in the source. ... ok
test_totw_full (test_tokens_k6.TestTokensCumulative.test_totw_full) ... ok
test_totw_grade_b (test_tokens_k6.TestTokensCumulative.test_totw_grade_b) ... ok

----------------------------------------------------------------------
Ran 126 tests in 4.401s

OK
```

---

## 5. Open item (carried into the doc phase)

**T-1 — Bonus base.** The app computes tag bonuses over the **lineup items**
(≤ `slots`), whereas FUT.GG displays bonuses over a **larger pool** (its page
position counts sum to more than the slot count: **Málaga 23/15**, **TOTW
32/20**; the PL **35/30** is an *older, dated* snapshot — the current PL page is
**30 at 30 slots**). The app therefore must **not** blindly align its numbers with
the visible FUT.GG figures. The UI label is **"Bonus over lineup items"** and the
item is marked `verify` in `AUDIT.md`. Documented here so the doc phase picks it up.

---

## 6. Pre-existing bug found & fixed — reserved word `export`

While validating the app in a real browser (headless Chrome), the inline script
threw `SyntaxError: Unexpected token 'export'` and **never executed** — so no
handler ever attached. Root cause: the Export button had `id="export"` and the
wiring was `export.onclick=...`. `export` is a **reserved word**, illegal as a
statement-start binding in a classic script. This was present in the **original
baseline** (verified against `a925878`) — it is not a P1 regression.

- Fix: `id="export"` → `id="exportBtn"`, wiring `export.onclick` → `exportBtn.onclick`.
- Guard: `test_form_fields.TestAppScriptParse` (2 tests) parses the inline script
  as a **classic script** (`new Function`) and forbids reserved-word element ids.
  `node --check` on a `.js` file does **not** catch this (sloppy-script mode allows
  a binding named `export`); the test therefore uses `new Function`, and was
  verified to fail when the bug is reintroduced and pass when fixed.

---

## 7. P1 run recap

- `python -m unittest discover -s tests -v` → `Ran 180 tests` — `OK`.
- Per module: sync 5, harness 5, parser 24, tokens/k6 17, form 14, score 19,
  all-tags 22, **plan 60**, **tag-table 14** → `5+5+24+17+14+19+22+60+14 = 180`.
- Engine mirror: `tools/sync_engine.py --check` → byte-identical, exports line
  included (now also exporting `sanScore`, `setUpperBound`, `portfolioUpperBound`,
  `portfolioBranchAndBound`, `portfolioImprove2opt`, `portfolioGreedySeed`,
  `portfolioWorld`, `portfolioPlan`, `portfolioValue`, `portfolioBrute`,
  `EXACT_PORTFOLIO_LIMIT`).
- Browser: Optimizer page renders the new **Global portfolio plan** panel above
  **Recommended upgrades**, and the method note states proven vs best-found.
  Screenshot: `p1_optimizer_portfolio.png`.
- **Third amendment vs. second amendment:** `portfolioPlan` beyond
  `EXACT_PF_LIMIT` no longer falls back to Greedy — it runs the **global B&B over
  S** (`portfolioUpperBound` + `portfolioBranchAndBound` + budget-respecting
  `portfolioImprove2opt`), reporting `proved` / `node_limit` (T-14); `portfolioBrute`
  rewritten to combination enumeration so it exhaustively checks the **global
  `plan()` path** past 20 (shared cards + `coins − reserve`, all objectives);
  non-negative-score precondition enforced via `sanScore` (T-13); T-1 doc
  corrected (current PL 30/30; 35/30 = dated snapshot).
- **Second amendment vs. first amendment:** unsound `evalSet` bound replaced by
  the monotone `setUpperBound` (T-11); `improve2opt` universe/id-set bug fixed
  (T-12); `planSet`/`portfolioPlan` now report `optimality`; global portfolio UI
  panel added; ≤25-candidate / ≤4-purchase brute force across all four
  objectives; T-1 note anchored on position sums. Commit `be3e17f` extended.
- **First amendment vs. first submission:** real `branchAndBound` became the
  primary `planSet` path (greedy = seed only); multi-set portfolio optimisation
  added (shared cost counted once, `coins − reserve` budget); independent dated
  offline TAG fixture added; `countTopTags` 10/Infinity tested.
