# VERIFICATION.md — P0 acceptance evidence

This file records the **reproducible evidence** for the P0 deliverables. Every
number and every green line below comes from an actual run of the suite in this
repository — nothing here is estimated or copied from an earlier draft.

- **Command:** `python -m unittest discover -s tests -v`
- **Result:** `Ran 104 tests` — `OK`
- **Runtime:** ~2.5 s
- **Node:** used by the K1 harness (`tools/engine_cli.js`); if `node` is absent,
  `test_sync_engine.TestEngineLoadable.test_loadable` is skipped but
  `test_bytes_equal` still runs (R4/F5).

---

## 1. Test count — corrected and reconciled

The earlier P0 report said "53" and listed a `test_sync_engine` count of 6. Both
were wrong. The corrected, per-module breakdown below sums **exactly** to the
discovered total:

| Module | Tests |
|---|---|
| `test_sync_engine.py` | **5** |
| `test_engine_harness.py` | 5 |
| `test_parser.py` | 24 |
| `test_tokens_k6.py` | **17** |
| `test_form_fields.py` | 12 |
| `test_score.py` | 19 |
| `test_all_tags.py` | 22 |
| **Total** | **104** |

`5 + 5 + 24 + 17 + 12 + 19 + 22 = 104` ✅ matches `discover`.

Two corrections vs. the earlier report:

1. **`test_sync_engine` = 5, not 6.** The five tests are:
   `test_bytes_equal`, `test_loadable`, `test_exports_line_included_in_block`,
   `test_markers_single_and_ordered`, `test_block_is_side_effect_free`.
   (The earlier "6" double-counted a parametrisation that does not exist.)
2. **`test_tokens_k6` grew 11 → 17** with the five `TestEligibilityIds` tests
   plus the originally-counted eleven (8 cumulative + 4 Multiples + 5 ids = 17;
   one `TestTokensCumulative` case, `test_totw_grade_b`, was already present).

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

## 4. Raw verbose output (verbatim)

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
Ran 104 tests in 2.556s

OK
```

> The block above is filled from `VERIFICATION_RAW.txt`, which is the
> unedited stdout+stderr of
> `python -m unittest discover -s tests -v` (exit code 0).
> Regenerate it any time with:
>
> ```sh
> python -m unittest discover -s tests -v | tee VERIFICATION_RAW.txt
> ```

---

## 5. Open item (carried into the doc phase)

**T-1 — Bonus base.** The app computes tag bonuses over the **lineup items**
(≤ `slots`), whereas FUT.GG displays bonuses over a **larger pool** (its page
position counts sum to more than the slot count: 23/15, 35/30, 32/20). The app
therefore must **not** blindly align its numbers with the visible FUT.GG
figures. The UI label is **"Bonus over lineup items"** and the item is marked
`verify` in `AUDIT.md`. Documented here so the doc phase picks it up.
