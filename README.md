# FC 27 Gallery Optimizer

A local-first website for answering: **given the cards already in my Gallery history, live-ish prices, set thresholds and card scores, what should I buy next to gain the most Gallery Tokens / Gallery Score for the least expected coin loss?**

## Run it

### macOS
Double-click `run.command`, or from Terminal:

```bash
cd fc27_gallery_optimizer
python3 server.py
```

Then open `http://127.0.0.1:8765`.

You can also open `index.html` directly. Everything except the experimental FUT.GG URL importer works without the local server.

## What the optimizer does

- Tracks cards as **collected forever**, matching Gallery history behavior.
- Stores each card's Gallery item score, buy price, expected resale price, First Owner status, rarity, nation, club, league, position and special type.
- Implements all 21 current Gallery bonus tags.
- Floors each tag bonus separately and counts only the 10 biggest-paying tags.
- Computes a set's best lineup from your collected eligible cards.
- Calculates cumulative Gallery Token rewards by grade.
- Searches **multi-card bundles**, so a card is not ignored just because it gives 0 tokens by itself. This is important when you need 5–10 more cards before a set jumps a grade.
- Plan search is a real **Branch & Bound** over candidate card sets, using a memoized lineup evaluation and a **provably monotone upper bound** (`setUpperBound`), then a 2-opt refinement that also respects the coin budget.
- Every plan reports whether it is **proven optimal** (the search was exhausted under the bound) or only the **best found** because the node cap was hit — the app never silently presents a capped search as optimal.
- Renders a **global portfolio plan** across every set: each card is bought **once**, its coin cost is charged **once**, and the shared budget is **`coins − reserve`**. The benefit shown is aggregated over all sets. The portfolio is **exhaustively proven optimal** for small candidate universes (≤ 20 cards); **beyond 20 candidates it runs the same global Branch & Bound over the shared card set S** (greedy seed → B&B under the monotone bound → budget-respecting 2-opt) and reports `proved` (the search was exhausted) or `node_limit` (*best found* — the node cap tripped). It never silently falls back to Greedy and never claims optimality for a truncated search.
- Recalculates overlapping league/club sets after each planned bundle.
- Uses expected permanent coin loss = `buy price - 95% of expected resale` by default. The sale-tax rate is editable.

## Data you need

The app is only as good as its inputs. For each card, the key fields are:

- `score`: the Gallery Item Score (not OVR)
- `buyPrice` and `resalePrice`
- `collected`: whether it has ever passed through your club
- club / league / nation / rarity / position
- First Owner / Holographic / TOTW / Hero / Icon when relevant

For each Gallery set:

- number of slots
- D/C/B/A/S score thresholds
- cumulative Gallery Token reward at each grade (the sum of all grade rewards up
  to and including that grade — not the increment for that grade alone)
- eligibility (club, league, rarity, or custom; an `ids` gallery lists the exact
  member `itemId`s)

Use **Data & Sync → Download template** to get the JSON schema.

## FUT.GG import

The local server includes a best-effort importer for a FUT.GG Gallery-set URL. It currently targets **set metadata** (name, slots, thresholds, rewards). Player-card extraction is deliberately not assumed because FUT.GG can change page markup and some card data may be client-rendered.

The next useful integration is a Gallery-history snapshot importer from your FUT.GG / EA-connected account. Once we have a reliable export/snapshot format, it can feed directly into this optimizer without changing the optimization engine.

## Scoring references

The scoring model follows the current FUT.GG Gallery documentation and EA's Gallery explanation:

- https://www.fut.gg/fut-gallery/
- https://www.fut.gg/fut-gallery/tags/
- https://help.ea.com/articles/ea-sports-fc/gallery-hub/

FUT.GG notes that cards remain collected after sale, item scores + bonus tags determine the set score, each tag bonus is rounded down separately, and only the ten largest tag bonuses count. Grade/token definitions can change during the season, so import current set data rather than hard-coding every set forever.

## Important limitation

EA does not publish a complete public score-to-Gallery-Level table. The app therefore optimizes calculated Gallery Score and lets you enter a **target Gallery score** from your in-game progress bar rather than guessing the score needed for a level.

### Bonus base (T-1) — status: `verify`

The app computes tag bonuses over **your lineup items for a set** (at most
`slots` items). FUT.GG's set pages display bonuses computed over a **larger pool**.
The decisive evidence is not the tag count but the **position sums vs slots**: the
positions listed on a page sum to *more* than the set's slot count, and the
displayed bonus numbers move with those extra positions. Supporting pages:

- **Málaga** — 23 positions for 15 slots.
- **TOTW** — 32 positions for 20 slots.
- **Premier League** — an *older* snapshot showed 35 for 30; the **current page
  shows midfield + attack = 15 + 15 = 30 at 30 slots**, so 35/30 may only be
  cited as a dated snapshot (see T-5 in `AUDIT.md`), never as a live figure.

"Only the ten biggest tags pay" **without an item count** says nothing about pool
size — it is the position-sum/slot mismatch that shows FUT.GG computes over a
pool larger than the app's lineup. The two numbers therefore need not match, and
the app **must not** blindly align its output with the visible FUT.GG figures.
The UI accordingly labels this value **"Bonus over lineup items"**. This
assumption is tracked as an open item in `AUDIT.md` and must be re-checked
against the live site in the doc phase.

## Deploy on Render

This repository is deploy-ready for Render as a Python Web Service.

- Runtime: Python
- Build command: `echo No build step required`
- Start command: `python3 server.py --no-open`
- The server automatically binds to `0.0.0.0:$PORT` when Render supplies `PORT`.

A `render.yaml` Blueprint is included.
