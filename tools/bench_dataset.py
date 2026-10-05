#!/usr/bin/env python3
"""Deterministic benchmark dataset for P3 (stdlib only, no product dependency).

Generates the agreed P3 shape: **127 Gallery sets x 3,000 cards**. The same
dataset feeds BOTH P3 measurements -- the headless-engine benchmark
(`tools/bench_engine.py`) and the browser-interaction benchmark
(`tools/bench_browser.py`) -- so the two numbers are directly comparable.

Everything here is seeded (`random.Random(SEED)`), so two runs on two machines
produce byte-for-byte the same 127x3000 payload. That is the point: a benchmark
whose input drifts cannot be re-checked.

Card shape matches what the engine reads (see `engine/engine.js`): `score`,
`buyPrice`/`resalePrice` (dated snapshots, like the app writes), `club`,
`league`, `nation`, `special`, `position`, `weakFoot`, `skillMoves`,
`itemId`/`id`, `playerKey`. Gallery-set shape matches `setModal()`: `id`, `name`,
`slots`, `eligibility`, `thresholds`, `rewards`.

The generator deliberately mixes three set-eligibility kinds (club / league /
rarity) so the candidate pools differ per set -- a uniform world would flatter
the solver.
"""
import argparse
import json
import os
import random

SEED = 20261005  # frozen: the P3 measured dataset must be reproducible
CARDS = 3000
SETS = 127
PRICE_UPDATED_AT = "2026-10-05T00:00:00Z"  # fixed so snapshots don't look "stale"

# Clubs/leagues are plausible names, NOT claims about the real FC 27 database.
# The point of the benchmark is load, not fidelity of names.
CLUBS = ["Athletic Club", "Real Betis", "Sevilla FC", "Valencia CF", "Villarreal CF",
         "Real Sociedad", "CA Osasuna", "RC Celta", "RCD Mallorca", "Getafe CF",
         "Girona FC", "Rayo Vallecano", "UD Almeria", "Cadiz CF", "Elche CF",
         "RCD Espanyol", "CD Leganes", "Real Valladolid", "Deportivo Alaves",
         "CA Pamplona"]
LEAGUES = ["LALIGA EA SPORTS", "Premier League", "Serie A", "Bundesliga",
           "Ligue 1", "Eredivisie", "Liga Portugal", "Süper Lig"]
NATIONS = ["Spain", "England", "Italy", "Germany", "France", "Netherlands",
           "Portugal", "Turkey", "Brazil", "Argentina"]
POSITIONS = ["GK", "CB", "LB", "RB", "CDM", "CM", "CAM", "LM", "RM", "ST", "LW", "RW"]
RARITIES = ["Bronze", "Silver", "Gold"]
SPECIALS = ["", "", "", "", "Hero", "Heroic", "Icon", "TOTW"]  # mostly base cards
GRADES = ["D", "C", "B", "A", "S"]


def _buy_price(rng, kind="normal"):
    """A dated BUY price snapshot, exactly the shape the app/server writes."""
    if kind == "silver":
        value = rng.randrange(200, 2500, 50)
    elif kind == "gold":
        value = rng.randrange(800, 45000, 100)
    else:
        value = rng.randrange(400, 12000, 50)
    return {
        "value": value,
        "best": int(value * 1.15),
        "worst": int(value * 0.80),
        "priceUpdatedAt": PRICE_UPDATED_AT,
        "fetchedAt": PRICE_UPDATED_AT,
        "source": "bench-synthetic",
    }


def _resale_price(rng, buy_value):
    """A resale snapshot that is usually BELOW the buy price.

    `loss = buy - floor(resale * (1 - tax))`. If resale >= buy the loss is 0,
    and under the `eff` objective `objectiveValue` divides by `max(1, loss)` --
    a zero-loss card with a token gain then scores ~1e6, the admissible bound
    stops pruning, and the search degenerates. That is a property of the INPUT,
    not of the engine: real cards almost always resell below their buy price.
    So the generator models a realistic spread where only a minority of cards
    break even or profit (a flipping edge), keeping `loss > 0` for most rows.
    """
    roll = rng.random()
    if roll < 0.06:          # 6% small profit (a genuine flip)
        mult = rng.uniform(1.02, 1.12)
    elif roll < 0.14:        # 8% break-even-ish
        mult = rng.uniform(0.96, 1.0)
    else:                    # 86% a real loss, as in a normal market
        mult = rng.uniform(0.55, 0.93)
    value = max(50, int(buy_value * mult))
    value = int(round(value / 50.0)) * 50
    return {
        "value": value,
        "best": int(value * 1.15),
        "worst": int(value * 0.80),
        "priceUpdatedAt": PRICE_UPDATED_AT,
        "fetchedAt": PRICE_UPDATED_AT,
        "source": "bench-synthetic",
    }


def build(seed=SEED, cards=CARDS, sets=SETS):
    """Return {"set": [...], "players": [...]} -- deterministic for a given seed."""
    rng = random.Random(seed)

    players = []
    for i in range(cards):
        rarity = RARITIES[i % len(RARITIES)]
        if rarity == "Gold":
            base_score = rng.randrange(70, 92)
            price_kind = "gold"
        elif rarity == "Silver":
            base_score = rng.randrange(58, 76)
            price_kind = "silver"
        else:
            base_score = rng.randrange(45, 65)
            price_kind = "silver"
        # Some rows carry an inflated score to exercise the top-10 tag cut.
        if i % 37 == 0:
            base_score += rng.randrange(10, 25)
        name = "%s %s" % (rng.choice(["Alex", "Bruno", "Carlos", "Diego", "Enzo",
                                      "Felix", "Gustavo", "Hugo", "Ivan", "Jonas",
                                      "Kevin", "Luis", "Marco", "Nico", "Oscar"]),
                          "%d" % (i + 1))
        club_name = CLUBS[i % len(CLUBS)]
        buy = _buy_price(rng, price_kind)
        p = {
            "id": "c%05d" % i,
            "itemId": "c%05d" % i,
            "playerKey": "player-%04d" % (i % 1800),  # some players have 2 cards
            "name": name,
            "score": base_score,
            "buyPrice": buy,
            "resalePrice": _resale_price(rng, buy["value"]),
            "priceFetchedAt": PRICE_UPDATED_AT,
            "collected": (i % 5 == 0),
            "firstOwner": (i % 11 == 0),
            "club": club_name,
            "league": LEAGUES[i % len(LEAGUES)],
            "nation": NATIONS[rng.randrange(len(NATIONS))],
            "rarity": rarity,
            "special": SPECIALS[i % len(SPECIALS)],
            "position": POSITIONS[i % len(POSITIONS)],
            "gender": "men" if i % 4 else "women",
            "weakFoot": (i % 5) + 1,
            "skillMoves": (i % 5) + 1,
            "holographic": (i % 23 == 0),
            "sets": [],
        }
        players.append(p)

    sets_list = []
    for j in range(sets):
        kind = ["club", "league", "rarity"][j % 3]
        if kind == "club":
            value = CLUBS[j % len(CLUBS)]
        elif kind == "league":
            value = LEAGUES[j % len(LEAGUES)]
        else:
            value = RARITIES[j % len(RARITIES)]
        slots = 15 if j % 4 else 20
        thresholds = {}
        rewards = {}
        # Rising thresholds: a set with all-zero thresholds is trivially maxed.
        step = rng.randrange(240, 620)
        for g, mult in zip(GRADES, (1, 2, 3, 4, 5)):
            thresholds[g] = int(step * mult) if g != "D" else 10
            rewards[g] = 0 if g == "D" else rng.randrange(4, 26)
        sets_list.append({
            "id": "g%03d" % j,
            "name": "%s %d" % (kind.capitalize(), j + 1),
            "slots": slots,
            "eligibility": {"type": kind, "value": value, "gender": "any"},
            "thresholds": thresholds,
            "rewards": rewards,
        })

    return {"set": sets_list, "players": players}


def build_state(seed=SEED, cards=CARDS, sets=SETS):
    """The full state the UI/server would receive (players + galleries + settings)."""
    d = build(seed=seed, cards=cards, sets=sets)
    return {
        "schemaVersion": 2,
        "settings": {"coins": 270000, "reserve": 0, "taxRate": 0.05,
                     "objective": "eff", "maxBundle": 15, "priceScenario": "base"},
        "players": d["players"],
        "galleries": d["set"],
    }


def main():
    ap = argparse.ArgumentParser(description="Generate the deterministic P3 benchmark dataset.")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--cards", type=int, default=CARDS)
    ap.add_argument("--sets", type=int, default=SETS)
    ap.add_argument("--out", default=None, help="write JSON state here (default: stdout summary)")
    a = ap.parse_args()
    state = build_state(seed=a.seed, cards=a.cards, sets=a.sets)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(state, fh, separators=(",", ":"))
        print("wrote %s (%d players, %d sets, %d bytes)"
              % (a.out, len(state["players"]), len(state["galleries"]),
                 os.path.getsize(a.out)))
    else:
        print(json.dumps({"players": len(state["players"]),
                          "galleries": len(state["galleries"]),
                          "seed": a.seed}))


if __name__ == "__main__":
    main()
