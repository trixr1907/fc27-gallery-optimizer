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
- Renders a **global portfolio plan** across every set: each card is bought **once**, its coin cost is charged **once**, and the shared budget is **`coins − reserve`**. The benefit shown is aggregated over all sets. The portfolio is **exhaustively proven optimal** for small candidate universes (≤ 20 cards); **beyond 20 candidates it runs the same global Branch & Bound over the shared card set S** (greedy seed → B&B under the monotone bound → budget-respecting 2-opt) and reports `proved` (the search was exhausted) or `node_limit` (*best found* — the search budget was spent). It never silently falls back to Greedy and never claims optimality for a truncated search.
- The **first calculation is one global portfolio search with a shared time budget** (default ≈ 2.5 s), not a per-set sweep, and it runs as a **cooperative step machine**: the page works in ~20 ms slices and stays responsive (the longest synchronous block is ~35 ms, including the initial render), showing a **"best found"** plan within tens of milliseconds and improving it as the search proceeds. Nothing blocks the main thread for seconds. **Per-set plans are computed on demand** ("Compute per-set plans"), one set per tick. "Improve further" **resumes the same search** (its state is preserved) instead of recomputing.
- The **collection table is virtualised**: only the visible window of cards is in the DOM, so a 3,000-card database renders in milliseconds instead of seconds. The per-set summary is computed progressively, in small batches, so the page paints immediately and the stats fill in.
- Recalculates overlapping league/club sets after each planned bundle.
- Uses expected permanent coin loss = `buy price - 95% of expected resale` by default. The sale-tax rate is editable.

## Prices and data are dated snapshots

Nothing in this tool treats a price as a timeless product value. A stored price is
a **dated snapshot** with an optional uncertainty spread:

```json
{
  "value": 1200, "best": 1100, "worst": 1400,
  "priceUpdatedAt": "2026-10-04T09:00:00.000Z", "source": "fut.gg"
}
```

- `value` (a.k.a. `base`) is the normal price; `best` / `worst` are the optimistic
  and conservative cases. A plain number is auto-wrapped with these fields on
  save/migration, so older exports keep working and `best`/`worst` default to base.
- The optimizer reads the **active price case** everywhere (`loss`, budget,
  feasibility, ranking). Set **Price case** to *Base*, *Worst case*
  (conservative) or *Best case* in the Settings panel — the whole plan is then
  computed for that case.
- `priceUpdatedAt` records when the price was read and `source` records where it
  came from. A snapshot older than **30 days** is surfaced as a **staleness
  warning** (⚠ in Data & Sync) so a stale price is never mistaken for a current one.
- The FUT.GG importer attaches the fetch time to the payload it returns, and a
  repeated fetch within the cache window is served from cache with `cached: true`
  and the **original** timestamp.
- Because prices move, any figure quoted in a report or fixture here is a **dated
  snapshot**, never a live value. The tag *model* (per-tag floor, top-10 cut) is
  stable; the tag *numbers* are not (see T-5 in `AUDIT.md`).

## Saved state, schema version and migration

Your saved data carries a `schemaVersion` (currently **2**) and is stored under a
**versioned key** (`fc27gallery.v2`). On the first load of an older payload the
legacy `fc27gallery` value is copied to **`fc27gallery.v0.bak`** *before*
migration, so an unwanted migration is always recoverable. A serialized state near
**4 MB** raises a non-blocking **size warning** (the browser storage limit is
approximate; export and trim if you get close).

On load and on JSON import the app migrates older data **forward**: bare prices
become snapshots (with `best`/`worst` filled from the base), legacy special values
are canonicalised, and missing fetch timestamps are filled in. Migration is
**idempotent** and **refuses** a file from a *newer* app version rather than
mis-reading it. The same rules are implemented on the server (`server.py`) and in
the UI (`index.html`), each tested separately.

## Importing a JSON snapshot (merge preview)

Importing a snapshot never silently overwrites what you edited. The app first
shows a **preview/diff** — what would be added, changed or left unchanged, field
by field — and tags each incoming record as **verified** (a trusted source) or
**estimated**. Any change to a field you plausibly edited by hand (a price, a
score, an item id) is **guarded**: it is *not* applied unless you explicitly
confirm, and you can choose to apply everything else while skipping those. The
FUT.GG set importer merges the same way.

## Local server hardening

When you run `python3 server.py`, the built-in importer is deliberately narrow:

- It only fetches the **exact host `www.fut.gg` over `https`**, with no userinfo,
  port or fragment, and only paths under `/fut-gallery/` (an allow-list, not a
  blocklist).
- The importer can be **disabled entirely** by setting `FC27_NO_IMPORT=1`, and it
  is **rate-limited** per client (30 requests / 60 s → `429`).
- Static file serving rejects path traversal and absolute/NUL paths, **never lists
  a directory**, and refuses any path that resolves outside the static root.
- Responses are capped (oversized upstream pages are rejected, `413`), only the
  needed HTTP methods are allowed (`405` otherwise), security headers
  (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`) are always sent, and API responses are
  `Cache-Control: no-store` (they carry dated snapshots).
- Fetch failures return a generic `502` with no stack trace.

You can ignore all of this if you only open `index.html` directly — everything
except the FUT.GG URL importer works fully offline.

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
