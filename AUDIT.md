# AUDIT.md — open assumptions and verification items

Living list of things the app *assumes* about FC 27 / FUT.GG that are **not**
proven by a fixture or the live site. Each entry has a status; do not treat an
`verify` entry as settled.

| ID | Topic | Assumption | Status | Where |
|---|---|---|---|---|
| T-1 | Bonus base | Tag bonuses are computed over the **lineup items** (≤ `slots`), not over FUT.GG's larger on-page pool (page positions sum > slots: 23/15, 35/30, 32/20). The app must not blindly align with visible FUT.GG figures. | `verify` | README §"Bonus base (T-1)"; UI label "Bonus over lineup items" |
| T-2 | Slots cascade | When a set page states no slot count, slots are taken from the body text, then an index oracle (`{totw: 20}`), then default 15; recorded via `slotsEstimated` / `slotsSource`. | `verify` | `server.py` `parse_futgg`; `tests/test_parser.py::TestSlotsEligibility` |
| T-3 | Score→Level | EA publishes no complete score-to-Gallery-Level table, so the app optimizes Gallery Score and takes a target score as input. | `accepted` | README §"Important limitation" |
| T-4 | Reward = tokens | A grade reward counts as tokens only when a `gallery-token` image is present; otherwise reward 0 + `rewardText` (H6). | `verify` | `tests/test_parser.py::TestGradeTable` |

## How to close a `verify` item

1. Re-fetch the relevant live page (or obtain an official statement).
2. Add or update a parse fixture under `tests/fixtures/futgg/`.
3. Add/refresh a parser test **and** (where the claim is about engine behavior) an
   engine assertion in `tests/`.
4. Flip the status here and record the evidence in `VERIFICATION.md`.
