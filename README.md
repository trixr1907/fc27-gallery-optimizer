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
- incremental Gallery Token reward at each grade
- eligibility (club, league, rarity, or custom)

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

## Deploy on Render

This repository is deploy-ready for Render as a Python Web Service.

- Runtime: Python
- Build command: `echo No build step required`
- Start command: `python3 server.py --no-open`
- The server automatically binds to `0.0.0.0:$PORT` when Render supplies `PORT`.

A `render.yaml` Blueprint is included.
