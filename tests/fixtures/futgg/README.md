# Offline FUT.GG fixtures

Dated snapshots of FUT.GG FUT Gallery pages, trimmed to the sections the parser
needs. They make the parser testable **without network access** (CI must be green
offline).

## Rules

* **Source & date:** each file starts with a comment
  `offline fixture: <name> | fetched <date> | source <url>`.
* **Trimmed on purpose:** only `<title>`, `<meta name="description">`, the
  `Grade requirements &amp; rewards` heading, the grade `<table>` (rows carry
  `data-gallery-reward="X"`), and the `Requires … players to complete`
  sentences are kept. Presentational `class`/`style`/`data-slot` attributes are
  stripped to keep the files small.
* **ToS:** these are small, personal-use excerpts for testing a local tool. Do
  not redistribute or expand them into full page copies.
* **Do not edit by hand** to make a test pass — fix the parser or recapture.

## Files

| File | Kind | Key expectations (parsed) |
| --- | --- | --- |
| `malaga_cf.html` | set page (club) | slots 15 (description, not estimated); club `Malaga CF`, gender `men`; thresholds 10/300/400/700/900; rewards 0/0/5/8/15 → Σ **28**; D=Badge, C=Kit (reward 0 + rewardText) |
| `premier_league.html` | set page (league) | slots 30 (description); league `Premier League`; thresholds 10/400k/800k/1.9M/4M; rewards 10/35/50/70/100 → Σ **265** |
| `totw.html` | set page (rarity) | **no number in description** → slots **20** via index oracle, `slotsEstimated: true`; rarity `TOTW`; thresholds 10/125k/175k/300k/550k; rewards 5/15/30/50/75 → Σ **175** |
| `rarities_index.html` | index/category page | rejected, `reason=index_page` |
| `premier_league_index.html` | index/category page | rejected, `reason=index_page` |
| `leagues_index.html` | index/category page | rejected, `reason=index_page` |

## Page-detection signals (K3)

A **set page** has, after `html.unescape`:

1. the `<title>` containing `FUT Gallery Set:` (singular + colon), **and**
2. the body containing the unescaped marker `Grade requirements & rewards`.

Index pages use `FUT Gallery Sets:` (plural) and have no grade table → `index_page`.

## Numbers NOT frozen here

`27.200` / `1.360` (seen on some pages) yield **0 hits** in the static HTML →
`unverified`; no fixture and no assertion for them (K5). Score strings in the
"Cheapest lineup" box (e.g. "Score 908/900") are **not** part of this data.

## Engine assertions

These fixtures drive **parser** tests only. Engine correctness is proven against
constructed fixtures + brute force (R5) — never against FUT.GG market-dependent
values such as "best possible grade today is C".
