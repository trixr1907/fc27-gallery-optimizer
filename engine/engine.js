// ===== ENGINE START =====
// FC 27 Gallery Optimizer — pure, side-effect-free engine.
// This block is byte-identical in index.html and engine/engine.js.
// It must NOT touch the DOM, localStorage, or any global `state`.
// Every function takes its inputs as explicit parameters.

// Grade order, weakest -> strongest.
const G = ['D', 'C', 'B', 'A', 'S'];

// Bonus tag tiers: [minItems, maxItems, percentage].
// Frozen fixture: FUT.GG /fut-gallery/tags/ "21 tags", "Updated 27 Sept 2026".
const TAG = {
  sameNation: [[5, 9, .01], [10, 19, .02], [20, 999, .04]],
  differentNation: [[5, 9, .01], [10, 19, .02], [20, 999, .04]],
  sameClub: [[5, 9, .01], [10, 19, .02], [20, 999, .04]],
  differentClub: [[5, 9, .01], [10, 19, .02], [20, 999, .04]],
  sameLeague: [[5, 9, .01], [10, 19, .02], [20, 999, .08]],
  differentLeague: [[5, 9, .01], [10, 19, .02], [20, 999, .04]],
  bronze: [[5, 9, .20], [10, 19, .40], [20, 999, .80]],
  silver: [[5, 9, .15], [10, 19, .30], [20, 999, .60]],
  gold: [[5, 9, .01], [10, 19, .02], [20, 999, .04]],
  holographic: [[2, 3, .08], [4, 5, .12], [6, 999, .20]],
  icon: [[2, 3, .10], [4, 5, .15], [6, 999, .25]],
  hero: [[2, 3, .08], [4, 5, .12], [6, 999, .20]],
  totw: [[3, 5, .04], [6, 9, .08], [10, 999, .15]],
  first: [[5, 9, 1.5], [10, 19, 3], [20, 999, 5]],
  gk: [[3, 5, .03], [6, 9, .06], [10, 999, .15]],
  multi: [[2, 2, .10], [3, 3, .15], [4, 999, .20]],
  wf: [[3, 4, .03], [5, 9, .06], [10, 999, .12]],
  skills: [[3, 4, .03], [5, 9, .06], [10, 999, .12]],
  def: [[5, 9, .03], [10, 14, .06], [15, 999, .10]],
  mid: [[5, 9, .03], [10, 14, .06], [15, 999, .10]],
  att: [[5, 9, .03], [10, 14, .06], [15, 999, .10]]
};

// Number of active tag bonuses that actually pay. FUT.GG set pages state
// verbatim "Only the ten biggest tags pay." -> default 10, configurable.
const DEFAULT_COUNT_TOP_TAGS = 10;

// Percentage for a tag rule at a given matched-item count, else 0.
function pct(rule, n) {
  for (const [a, b, p] of TAG[rule] || []) if (n >= a && n <= b) return p;
  return 0;
}

// A Gallery item score is a NON-NEGATIVE quantity. `sanScore` enforces that at
// the engine boundary: NaN / missing -> 0, negatives -> 0. This is the
// precondition `setUpperBound` relies on (its base term is Σ of the <=slots
// largest scores; with negative scores that term is neither monotone nor an
// upper bound on a realised subset, which would corrupt B&B pruning -- see
// AUDIT T-13). Sanitising here makes every downstream score read consistent.
function sanScore(x) {
  const v = +x;
  return Number.isFinite(v) && v > 0 ? v : 0;
}

// Core bonus primitive: floor(sum of matched item scores * pct).
// Extracted as a standalone function so unit tests can target it directly.
function bonus(matchedItems, p) {
  if (!p) return 0;
  const sum = matchedItems.reduce((s, x) => s + sanScore(x.score), 0);
  return Math.floor(sum * p);
}

// Largest single group for a keyed attribute (e.g. same nation).
function group(items, key, rule) {
  const m = {};
  items.forEach(p => { if (p[key]) (m[p[key]] ??= []).push(p); });
  let best = 0;
  for (const a of Object.values(m)) {
    const q = pct(rule, a.length);
    const b = bonus(a, q);
    if (b > best) best = b;
  }
  return best;
}

// One entry per distinct key value (counts toward "different X" tags).
function distinct(items, key, rule) {
  const m = {};
  items.forEach(p => { if (p[key] && (!m[p[key]] || +p.score > +m[p[key]].score)) m[p[key]] = p; });
  const a = Object.values(m), q = pct(rule, a.length);
  return bonus(a, q);
}

// Flat filtered set (e.g. all Silver cards).
function filt(items, fn, rule) {
  const a = items.filter(fn), q = pct(rule, a.length);
  return bonus(a, q);
}

// Full tag breakdown for a list of items. Returns { base, bonus, total, tags }.
// opts.countTopTags controls how many tag bonuses pay (default 10; Infinity = all).
function score(items, opts) {
  const countTopTags = opts && opts.countTopTags != null ? opts.countTopTags : DEFAULT_COUNT_TOP_TAGS;
  const base = items.reduce((s, p) => s + sanScore(p.score), 0);
  const b = [];
  const add = x => { if (x > 0) b.push(x); };
  add(group(items, 'nation', 'sameNation'));
  add(distinct(items, 'nation', 'differentNation'));
  add(group(items, 'club', 'sameClub'));
  add(distinct(items, 'club', 'differentClub'));
  add(group(items, 'league', 'sameLeague'));
  add(distinct(items, 'league', 'differentLeague'));
  add(filt(items, p => p.rarity === 'Bronze', 'bronze'));
  add(filt(items, p => p.rarity === 'Silver', 'silver'));
  add(filt(items, p => p.rarity === 'Gold', 'gold'));
  add(filt(items, p => p.holographic, 'holographic'));
  add(filt(items, p => p.special === 'Icon', 'icon'));
  add(filt(items, p => p.special === 'Hero' || p.special === 'Heroic', 'hero'));
  add(filt(items, p => p.special === 'TOTW' || p.special === 'Team of the Week', 'totw'));
  add(filt(items, p => p.firstOwner, 'first'));
  add(filt(items, p => p.position === 'GK', 'gk'));
  // Multiples!: 2+ items of the same player (playerKey = canonical player id).
  const mm = {};
  items.forEach(p => (mm[p.playerKey || p.name] ??= []).push(p));
  for (const a of Object.values(mm)) add(bonus(a, pct('multi', a.length)));
  add(filt(items, p => +p.weakFoot >= 5, 'wf'));
  add(filt(items, p => +p.skillMoves >= 5, 'skills'));
  add(filt(items, p => ['CB', 'LB', 'RB'].includes(p.position), 'def'));
  add(filt(items, p => ['CDM', 'CM', 'CAM', 'LM', 'RM'].includes(p.position), 'mid'));
  add(filt(items, p => ['ST', 'LW', 'RW'].includes(p.position), 'att'));
  b.sort((a, c) => c - a);
  const paying = Number.isFinite(countTopTags) ? b.slice(0, countTopTags) : b.slice();
  const bonusTotal = paying.reduce((a, c) => a + c, 0);
  return { base, bonus: bonusTotal, total: base + bonusTotal, tags: b };
}

// Eligibility of a card for a set. Tolerant string comparison via norm().
function eligible(p, g) {
  const e = g.eligibility || {};
  if (e.gender && e.gender !== 'any' && p.gender !== e.gender) return false;
  if (e.type === 'club') return norm(p.club) === norm(e.value);
  if (e.type === 'league') return norm(p.league) === norm(e.value);
  if (e.type === 'rarity') return norm(p.special || p.rarity) === norm(e.value);
  if (e.type === 'ids') return (e.ids || []).includes(p.itemId || p.id);
  return (p.sets || []).includes(g.id);
}

// Normalization for tolerant name/type comparison (accents, club prefixes, aliases).
function norm(s) {
  if (s == null) return '';
  let t = String(s).toLowerCase().trim();
  t = t.normalize('NFD').replace(/[\u0300-\u036f]/g, ''); // strip accents
  const alias = {
    'team of the week': 'totw',
    'heroes': 'heroic',
    'hero': 'heroic',
    'holographics': 'holographic',
    'holographic': 'holographic'
  };
  if (alias[t]) return alias[t];
  // Drop common club suffixes/prefixes so "Málaga CF" == "Malaga CF".
  t = t.replace(/\b(fc|cf|sc|ac|afc|club|de futbol|futbol)\b/g, ' ');
  return t.replace(/\s+/g, ' ').trim();
}

// Best lineup of <= n items. Greedy seed + hill-climb swap. Deterministic.
// K6 identity model:
//   itemId    = identity of one CARD (two card versions of a player differ).
//   playerKey = canonical PLAYER (used only by "Multiples!").
//   `id` is the app's per-row record id and is only a last-resort stand-in for
//   a missing itemId -- never the canonical player identity.
// The pool is de-duped by itemId first, so no two lineup items share a card.
// Two items of the same player (same playerKey) are allowed and both kept.
function lineup(pool, n) {
  const byId = new Map();
  for (const p of pool) {
    const k = p.itemId || p.id;
    const prev = byId.get(k);
    if (!prev || sanScore(p.score) > sanScore(prev.score)) byId.set(k, p);
  }
  pool = [...byId.values()];
  if (pool.length <= n) return { items: pool.slice(), ...score(pool) };
  const cur = pool.slice().sort((a, b) => sanScore(b.score) - sanScore(a.score)).slice(0, n);
  let cs = score(cur).total, curIds = new Set(cur.map(x => x.itemId || x.id));
  for (let k = 0; k < 5; k++) {
    let best = null;
    for (let i = 0; i < n; i++) {
      for (const c of pool) {
        const cid = c.itemId || c.id;
        if (curIds.has(cid)) continue;
        const t = cur.slice(); t[i] = c;
        const s = score(t).total;
        if (s > cs && (!best || s > best.s)) best = { i, c, s };
      }
    }
    if (!best) break;
    curIds.delete(cur[best.i].itemId || cur[best.i].id);
    cur[best.i] = best.c;
    curIds.add(best.c.itemId || best.c.id);
    cs = best.s;
  }
  return { items: cur, ...score(cur) };
}

// Highest grade reached given a score, or null if the set is not yet completable.
function grade(g, count, s) {
  if (count < g.slots) return null;
  let z = null;
  for (const x of G) if (s >= +(g.thresholds ?.[x] ?? Infinity)) z = x;
  return z;
}

// Cumulative Gallery Tokens: sum of each grade's reward up to and including `gr`.
function tokens(g, gr) {
  if (!gr) return 0;
  let n = 0;
  for (const x of G) {
    n += +(g.rewards ?.[x] || 0);
    if (x === gr) break;
  }
  return n;
}

// Expected permanent coin loss = buy - (1 - tax) * resale, floored, clamped >= 0.
function loss(p, taxRate) {
  const buy = +p.buyPrice || 0;
  const res = +p.resalePrice || buy;
  return Math.max(0, buy - Math.floor(res * (1 - (taxRate ?? 0.05))));
}

// Evaluate one set against a player list.
function evalG(g, players) {
  const pool = players.filter(p => p.collected && eligible(p, g));
  const l = lineup(pool, +g.slots || 15);
  const gr = grade(g, l.items.length, l.total);
  return { ...l, count: pool.length, grade: gr, tokens: tokens(g, gr), complete: pool.length >= g.slots };
}

// Aggregate over all sets. Returns { tokens, score, evals }.
function summary(galleries, players) {
  let t = 0, s = 0;
  const e = {};
  galleries.forEach(g => {
    const x = evalG(g, players);
    e[g.id] = x;
    t += x.tokens;
    if (x.complete) s += x.total;
  });
  return { tokens: t, score: s, evals: e };
}

// ---- P1 (R3): shopping plan -------------------------------------------------
// All functions below are pure: same input -> same output, no globals, no I/O.
// `collectedIds` is a Set of itemIds (or record ids) the user already owns.

// The usable pool for a set: collected, eligible, de-duped by itemId (best score
// kept, matching lineup()). Purely collected cards -- buys are never in a pool.
function poolFor(g, players, collectedIds) {
  const byId = new Map();
  for (const p of players) {
    if (((collectedIds && collectedIds.has(p.itemId || p.id)) || p.collected) && eligible(p, g)) {
      const k = p.itemId || p.id, prev = byId.get(k);
      if (!prev || sanScore(p.score) > sanScore(prev.score)) byId.set(k, p);
    }
  }
  return [...byId.values()];
}

// Buyable candidates for a set: owned, eligible, priced, de-duped by itemId.
function candidatesFor(g, players, collectedIds) {
  const byId = new Map();
  for (const p of players) {
    if ((collectedIds && collectedIds.has(p.itemId || p.id)) || p.collected) continue;
    if (!eligible(p, g) || !(+p.buyPrice > 0)) continue;
    const k = p.itemId || p.id, prev = byId.get(k);
    if (!prev || sanScore(p.score) > sanScore(prev.score)) byId.set(k, p);
  }
  return [...byId.values()];
}

// Memoized set evaluation (R3). The cache key MUST encode not just the requested
// itemId set but the ACTUAL items it resolves to in `pool` -- two different pools
// can map the same id to different cards, or omit it entirely, and would
// otherwise collide (e.g. `pool` vs `pool ∪ candidates ∪ units`). We therefore
// key on the resolved, sorted contribution of every selected item.
// The cache is BOUNDED (LRU-ish by insertion order) so a long browser session
// cannot grow it without limit. `evalMemoReset()` clears it between searches.
const _evalMemo = new Map();
const _EVAL_MEMO_MAX = 200000;
function evalMemoReset() { _evalMemo.clear(); }
// Canonical, order-independent signature of one item as the scorer sees it.
function _itemSig(x) {
  return [x.itemId || x.id, sanScore(x.score), x.playerKey || x.name || '',
    x.nation || '', x.club || '', x.league || '', x.rarity || '',
    x.position || '', x.special || '',
    x.holographic ? 1 : 0, x.firstOwner ? 1 : 0,
    +x.weakFoot || 0, +x.skillMoves || 0].join('\u0001');
}
function _idSetSig(idSet) { return [...idSet].sort().join(','); }
function evalSet(g, pool, idSet) {
  const items = pool.filter(p => idSet.has(p.itemId || p.id));
  // Key = set identity + slots + the resolved items (not just the requested ids).
  const key = g.id + '|' + (+g.slots || 0) + '|' + _idSetSig(idSet)
    + '||' + items.map(_itemSig).sort().join('\u0002');
  const hit = _evalMemo.get(key);
  if (hit !== undefined) return hit;
  const l = lineup(items, +g.slots || 15);
  const r = { score: l.total, base: l.base, bonus: l.bonus, grade: grade(g, l.items.length, l.total), count: items.length };
  if (_evalMemo.size >= _EVAL_MEMO_MAX) _evalMemo.clear();
  _evalMemo.set(key, r);
  return r;
}

// Marginal gain of buying item `x` (already in the items list), holding the rest
// fixed. `gain >= 0` is required for the marginal-greedy seed to be sound.
function gain1(g, items, x) { return score(items.concat([x])).total - score(items).total; }

// ---- Branch & Bound over candidate card sets S (R3) --------------------------
// Node `S` is a subset of the priced candidates (by itemId). We maximise the
// objective of buying S, where the realised score is the LINEUP score capped at
// `slots` (evalSet), and cost = sum(buyPrice) with a coin-budget constraint.
//
// `evalPool` is the FIXED evaluation universe (owned ∪ units ∪ all candidates):
// evalSet can only select items present in its pool, so candidates MUST be in it
// for a purchased card to enter the lineup.
//
// ---------------------------------------------------------------------------
// ADMISSIBLE UPPER BOUND (why it must NOT be `evalSet` over the whole pool)
// ---------------------------------------------------------------------------
// `lineup()` is a HEURISTIC selector (top-N by score + a bounded 5-pass swap
// search), so it is NOT monotone in the pool: a larger pool can make it settle
// on a worse tag-synergistic subset than a smaller pool would. Counter-example
// (reproduced in tests): lineup(P) = 1723 but lineup(P \ {p6}) = 1888. Therefore
// "evalSet over all remaining candidates" is NOT an admissible upper bound and
// would let the search prune away the true optimum.
//
// We instead use a bound built from two terms that ARE provably monotone in the
// pool, and each an upper bound on the corresponding part of any realised lineup:
//   base ≤ Σ (up to `slots` largest base scores)        [picking at most `slots`]
//   bonus ≤ score(pool).bonus with ALL tags uncapped    [`score` only ever ADDS
//           positive per-tag floors as items join; capping to the top 10 at the
//           subset level can only lower it, so the uncapped pool bonus dominates]
// Both terms are monotone non-decreasing when items are added, hence `setUpperBound`
// is a valid, monotone upper bound. Verified exhaustively by `test_plan`.
//
// PRECONDITION (AUDIT T-13): both terms assume NON-NEGATIVE item scores. With a
// negative score the "Σ of the <=slots largest scores" term is neither monotone
// nor an upper bound on a realised subset (empirically: 1563/2000 random pools
// produced a realised subset ABOVE the bound), which would corrupt pruning. We
// therefore (a) sanitise every score read through `sanScore`, and (b) build the
// bound from `sanScore` too, so a raw negative cannot make it unsound.
function setUpperBound(g, pool) {
  const n = +g.slots || 15;
  const baseScores = pool.map(p => sanScore(p.score)).sort((a, b) => b - a).slice(0, n);
  let base = 0;
  for (const s of baseScores) base += s;
  // Uncapped tag bonus over the whole pool: an upper bound on any subset's bonus.
  const bonus = score(pool, { countTopTags: Infinity }).bonus;
  return base + bonus;
}
function bbUpperBound(g, evalPool, S, opts) {
  return setUpperBound(g, evalPool);
}
function bbValue(g, evalPool, S, opts) {
  const idOf = x => x.itemId || x.id;
  const ids = new Set(evalPool.map(idOf));
  // S is a subset of evalPool; keep only the owned pool + the chosen cards.
  const chosenOnly = new Set((opts.ownedIds || []));
  for (const x of S) chosenOnly.add(idOf(x));
  const ev = evalSet(g, evalPool, chosenOnly);
  const totalLoss = S.reduce((s, p) => s + loss(p, opts.taxRate), 0);
  const dTokens = tokens(g, ev.grade) - (opts.baseTokens || 0);
  const dScore = ev.score - (opts.baseScore || 0);
  return { value: objectiveValue(opts.objective, dTokens, dScore, totalLoss), loss: totalLoss, dScore, dTokens, score: ev.score };
}
// Depth-first B&B. `cands` traversal order is deterministic. The greedy seed is
// evaluated first, so pruning can only discard nodes that cannot beat it.
// `maxNodes` caps work for large pools (the seed is always kept).
function branchAndBound(g, pool, unitsNeeded, cands, seed, opts) {
  const idOf = x => x.itemId || x.id;
  const maxBundle = Math.max(1, +opts.maxBundle || 15);
  const coins = +opts.coins != null ? +opts.coins : Infinity;
  const ownedIds = pool.concat(unitsNeeded).map(idOf);
  const baseIdSet = new Set(ownedIds);
  // evalPool = owned ∪ units ∪ candidates (deduped). Candidates must be present
  // so that a bought card can actually enter the lineup.
  const seen = new Set(), evalPool = [];
  for (const x of pool.concat(unitsNeeded).concat(cands)) {
    const id = idOf(x);
    if (seen.has(id)) continue;
    seen.add(id); evalPool.push(x);
  }
  const bopts = Object.assign({}, opts, { ownedIds });
  // Explore high-loss candidates first so expensive branches are bounded early.
  const order = cands.slice().sort((a, b) =>
    (loss(b, opts.taxRate) - loss(a, opts.taxRate)) || (b.score - a.score)
    || String(idOf(a)).localeCompare(String(idOf(b))));
  let best = (seed || []).slice();
  // The seed must itself be affordable; otherwise it is not a valid incumbent
  // (B&B would "return" an infeasible set that the caller then has to truncate,
  // losing the optimum). Drop an over-budget seed and start from the empty set.
  const seedCost = best.reduce((s, c) => s + (+c.buyPrice || 0), 0);
  if (seedCost > coins) best = [];
  let bestVal = bbValue(g, evalPool, best, bopts).value;
  let nodes = 0;
  // `aborted` becomes true as soon as the node cap is hit: the returned plan is
  // then the BEST FOUND so far, NOT proven optimal. `proved` is its negation.
  let aborted = false;
  const maxNodes = +opts.maxNodes > 0 ? +opts.maxNodes : 200000;
  const rec = (idx, S) => {
    if (aborted) return;
    if (++nodes > maxNodes) { aborted = true; return; }
    // Admissible bound: best possible score from here; if even that cannot beat
    // the incumbent, prune. (buyPrice >= 0, and the objective is monotone in
    // tokens then score, so a score-only bound is valid for every objective.)
    const ubScore = bbUpperBound(g, evalPool, S, bopts);
    const ubVal = objectiveValue(opts.objective, tokens(g, 'S') - (opts.baseTokens || 0),
      ubScore - (opts.baseScore || 0), 0);
    if (ubVal < bestVal) return;
    if (S.length >= maxBundle || idx >= order.length) return;
    for (let i = idx; i < order.length; i++) {
      const c = order[i];
      if (baseIdSet.has(idOf(c)) || S.some(x => idOf(x) === idOf(c))) continue;
      const spent = (opts.seedSpend || 0)
        + S.reduce((s, p) => s + (+p.buyPrice || 0), 0) + (+c.buyPrice || 0);
      if (spent > coins) continue; // hard coin-budget constraint
      const S2 = S.concat([c]);
      const v = bbValue(g, evalPool, S2, bopts).value;
      if (v > bestVal) { bestVal = v; best = S2.slice(); }
      rec(i + 1, S2);
    }
  };
  rec(0, []);
  return { best, value: bestVal, nodes, aborted, proved: !aborted, maxNodes };
}

// Objective from the raw signals. Deterministic, monotone in tokens then score.
//   tokens   : maximise expected tokens
//   score    : maximise Gallery score
//   balanced : tokens first, score as secondary tie-break
//   eff      : tokens per unit of expected coin loss (capital efficiency)
function objectiveValue(obj, dTokens, dScore, dLoss) {
  if (obj === 'tokens') return dTokens * 1e9 + dScore;
  if (obj === 'score') return dScore * 1e5 + dTokens * 1e6;
  if (obj === 'balanced') return dTokens * 1e7 + dScore * 100 - dLoss * 10;
  return (dTokens / Math.max(1, dLoss)) * 1e6 + dScore / Math.max(1, dLoss);
}

// 2-opt: drop up to two members, refill from the free candidates, keep any edit
// that raises the objective. Deterministic (first-improvement, stable order).
// Uses the SAME value function as the Branch & Bound search (tokens + score +
// loss) so refinement can never undo a token-improving edit.
function improve2opt(sel, pool, cands, g, opts) {
  const idOf = x => x.itemId || x.id;
  const baseTokens = opts.baseTokens || 0;
  const baseScore = opts.baseScore || 0;
  // The realised lineup ALWAYS contains the owned pool PLUS the selection, so
  // `valOf` must evaluate exactly that id set. Two bugs hid here: (a) the
  // eval-universe omitted the candidates, so they were invisible to `lineup()`;
  // (b) the id set omitted the owned pool, so the evaluated lineup dropped the
  // cards the user already owns. Either one can make the refinement discard a
  // correct B&B optimum. Fix: universe = owned ∪ cands ∪ sel, id set = owned ∪ list.
  const seen = new Set(), universe = [];
  for (const x of pool.concat(cands).concat(sel)) {
    const id = idOf(x);
    if (seen.has(id)) continue;
    seen.add(id); universe.push(x);
  }
  const poolIds = pool.map(idOf);
  const valOf = list => {
    const ids = new Set(poolIds);
    for (const x of list) ids.add(idOf(x));
    const ev = evalSet(g, universe, ids);
    const dTokens = tokens(g, ev.grade) - baseTokens;
    const dScore = ev.score - baseScore;
    const dLoss = list.reduce((s, p) => s + loss(p, opts.taxRate), 0);
    return objectiveValue(opts.objective, dTokens, dScore, dLoss);
  };
  // Coin budget: an edit that pushes spend above `opts.coins` is NOT a valid
  // improvement (B&B only ever returns affordable sets, so refinement must not
  // silently make the plan infeasible).
  const coins = +opts.coins != null ? +opts.coins : Infinity;
  const spendOf = list => list.reduce((s, p) => s + (+p.buyPrice || 0), 0);
  let cur = sel.slice(), curVal = valOf(cur);
  for (let pass = 0; pass < 4; pass++) {
    let best = null, bestVal = curVal;
    for (let i = 0; i < cur.length; i++) {
      for (let j = i; j < cur.length; j++) {
        const base = cur.slice(); base.splice(j, 1); if (i !== j) base.splice(i, 1);
        const used = new Set(base.map(idOf));
        for (const c of cands) {
          if (used.has(idOf(c))) continue;
          const cand = base.concat([c]);
          if (spendOf(cand) > coins) continue; // never leave the budget
          const v = valOf(cand);
          if (v > bestVal) { bestVal = v; best = cand; }
        }
      }
    }
    if (!best) break;
    cur = best; curVal = bestVal;
  }
  return cur;
}

// A single-set shopping plan.
//   base      : eval of the currently owned pool
//   owners    : number/capital of currently owned eligible items
//   units     : all unpriced "slot-filler" units needed first (free, zero loss)
//   cands     : priced candidates the plan selects from
//   recommendations = units + chosen cands, ranked
//   newEval   : eval after buying everything
//   feasible  : every chosen candidate fits within the coin budget
function planSet(g, players, opts) {
  opts = opts || {};
  const objective = opts.objective || 'eff';
  const taxRate = opts.taxRate;
  const maxBundle = Math.max(1, +opts.maxBundle || 15);
  const coins = +opts.coins != null ? +opts.coins : Infinity;
  const collectedIds = opts.collectedIds;
  const pool = poolFor(g, players, collectedIds);
  const n = +g.slots || 15;
  const base = { items: pool.slice(0, n), ...score(pool), count: pool.length };
  const baseScore = base.total;
  const baseTokens = tokens(g, grade(g, pool.length, baseScore));
  const cands = candidatesFor(g, players, collectedIds);
  // units = unpriced eligible items, used to fill slots before buying anything.
  const units = players.filter(p => !((collectedIds && collectedIds.has(p.itemId || p.id)) || p.collected)
    && eligible(p, g) && !(+p.buyPrice > 0));
  const slotsFree = Math.max(0, n - pool.length);
  const unitsNeeded = units.slice(0, slotsFree);
  const virtualCount = pool.length + unitsNeeded.length;

  // Greedy marginal seed over candidates, respecting the coin budget so the seed
  // is itself a valid incumbent. The seed only bounds the B&B search below; it
  // does NOT replace it (B&B explores every feasible subset up to maxBundle).
  const seedItems = pool.concat(unitsNeeded);
  const candsSorted = cands.slice().sort((a, b) => (b.score - a.score) || String(a.itemId || a.id).localeCompare(String(b.itemId || b.id)));
  let sel = [], seedSpend = 0;
  for (let k = 0; k < maxBundle; k++) {
    // pick the candidate with the greatest marginal gain that still fits the budget
    let best = null, bestGain = -1;
    for (const c of candsSorted) {
      if (sel.some(s => (s.itemId || s.id) === (c.itemId || c.id))) continue;
      if (seedSpend + (+c.buyPrice || 0) > coins) continue;
      const gv = gain1(g, seedItems.concat(sel), c);
      if (gv > bestGain || best === null) { bestGain = gv; best = c; }
    }
    if (!best) break;
    sel.push(best); seedSpend += (+best.buyPrice || 0);
  }
  // --- R3: Branch & Bound over candidate sets S --------------------------------
  // Primary search path: `branchAndBound` explores the space of priced card
  // subsets with the greedy result as its seed and the coin budget as a hard
  // constraint. The greedy seed only bounds the search; it does not replace it.
  // `evalSet` (memoized) is the evaluation oracle, so the realised score is the
  // LINEUP score capped at `slots`, never the raw sum of everything bought.
  // The admissible bound is `setUpperBound` (NOT evalSet over the whole pool --
  // `lineup()` is heuristic and not monotone, see the note above).
  const bbOpts = {
    objective, taxRate, baseTokens, baseScore, maxBundle, coins,
    seedSpend: 0, maxNodes: +opts.maxNodes > 0 ? +opts.maxNodes : 200000
  };
  const bb = branchAndBound(g, pool.concat(unitsNeeded), [], cands, sel, bbOpts);
  sel = bb.best;
  // `optimality` records whether the plan is PROVEN optimal (B&B exhausted the
  // search under its bound) or merely the best found because the node cap hit.
  const optimality = bb.proved ? 'proved' : 'node_limit';
  // B&B only ever returns coin-feasible sets (seed feasibility is validated and
  // every accepted node passes the budget check), so no truncation is needed.
  let filler = null;
  const shortage = n - virtualCount - sel.length;
  if (shortage > 0) {
    const usedIds = new Set([...pool, ...unitsNeeded, ...sel].map(x => x.itemId || x.id));
    const fpool = cands.filter(c => !usedIds.has(c.itemId || c.id) && (+c.buyPrice || 0) <= coins - spendTotal(sel))
      .sort((a, b) => (+a.buyPrice || 0) - (+b.buyPrice || 0) || (b.score - a.score));
    let acc = spendTotal(sel), picks = [];
    for (const c of fpool) { if (acc + (+c.buyPrice || 0) <= coins) { picks.push(c); acc += (+c.buyPrice || 0); } }
    filler = picks;
  }
  // 2-opt refinement against the real objective (upgrades only; fillers are slot fillers).
  sel = improve2opt(sel, pool.concat(unitsNeeded), cands, g, { objective, taxRate, baseTokens, baseScore, coins });
  const chosen = sel.slice().sort((a, b) => (b.score - a.score) || String(a.itemId || a.id).localeCompare(String(b.itemId || b.id)));
  const fillers = filler || [];
  const recs = unitsNeeded.concat(fillers).concat(chosen);
  // The realised score is the LINEUP score (capped at `slots`), not the raw sum
  // of everything bought -- extra items beyond `slots` do not add to the score.
  // `newEval` is the memoized, lineup-capped evaluation; `buyScore` is that total.
  const idOf = x => x.itemId || x.id;
  const newEval = evalSet(g, pool.concat(cands), new Set(pool.concat(recs).map(idOf)));
  const buyScore = newEval.score;
  const completeAfter = pool.length + recs.length >= n;
  const newGrade = newEval.grade;
  const dTokens = tokens(g, newGrade) - baseTokens;
  const dScore = buyScore - baseScore;
  const dLoss = chosen.concat(fillers).reduce((s, p) => s + loss(p, taxRate), 0);
  const feasible = spendTotal(chosen.concat(fillers)) <= coins;
  const recsSorted = recs.slice().sort((a, b) => {
    const uc = (x) => (+x.buyPrice > 0 ? 1 : 0); // units first (they are free)
    return (uc(a) - uc(b)) || ((+b.score || 0) - (+a.score || 0)) || String(a.itemId || a.id).localeCompare(String(b.itemId || b.id));
  });
  return {
    set: g.id, name: g.name, objective,
    base: { score: baseScore, tokens: baseTokens, grade: grade(g, pool.length, baseScore), count: pool.length },
    owners: pool.length, slots: n, virtualCount,
    units: unitsNeeded.map(x => x.itemId || x.id),
    filler: fillers.map(x => x.itemId || x.id),
    chosen: chosen.map(x => x.itemId || x.id),
    recommendations: recsSorted.map(x => x.itemId || x.id),
    dTokens, dScore, loss: dLoss,
    buyScore, newGrade, newTokens: tokens(g, newGrade), completeAfter,
    value: objectiveValue(objective, dTokens, dScore, dLoss),
    feasible,
    // Optimality report: 'proved' = B&B exhausted the search under its bound;
    // 'node_limit' = the node cap was hit, so this is the BEST FOUND plan.
    optimality, nodes: bb.nodes
  };
}
function spendTotal(items) { return items.reduce((s, p) => s + (+p.buyPrice || 0), 0); }

// ---- R3: portfolio optimisation across several sets --------------------------
// Buying ONE card can improve SEVERAL sets at once, so its coin loss must count
// only ONCE in the portfolio. The union-cost model below expresses exactly that:
//   * S      : the set of distinct itemIds bought (shared cards appear once)
//   * cost(S): sum of loss() over the DISTINCT cards -> never double-counted
//   * value(S): sum over every set g of the set's own objective, where the set's
//               score is the LINEUP score after adding the cards of S that are
//               eligible for g, and the loss term is passed as 0 (cost is a
//               portfolio-level constraint, counted once, not per set).
//
// `budget` is the usable capital AFTER the reserve is withheld:
//   budget = coins - reserve.
// The portfolio is proven optimal against brute force on constructed data.

// Build the shared candidate universe + per-set pools once. JSON-friendly.
//   pools[i] : usable pool for set i
//   prices   : Map itemId -> { card, setIds:Set<galleryId> } (which sets a card helps)
//   bases[i] : base { score, tokens } of set i (before buying)
//   cands    : de-duped candidate cards (union across sets)
function portfolioWorld(galleries, players, opts) {
  const gs = galleries || [];
  const collectedIds = opts && opts.collectedIds;
  const pools = gs.map(g => poolFor(g, players, collectedIds));
  const bases = gs.map((g, i) => {
    const pool = pools[i];
    const s = score(pool.slice(0, +g.slots || 15)).total;
    return { score: s, tokens: tokens(g, grade(g, pool.length, s)) };
  });
  const prices = new Map();
  for (const g of gs) {
    for (const c of candidatesFor(g, players, collectedIds)) {
      const id = c.itemId || c.id;
      const rec = prices.get(id) || { card: c, setIds: new Set() };
      if (!rec.setIds.has(g.id)) rec.setIds.add(g.id);
      if ((+c.score || 0) > (+rec.card.score || 0)) rec.card = c;
      prices.set(id, rec);
    }
  }
  return { gs, pools, bases, prices, cands: [...prices.keys()].map(id => prices.get(id).card) };
}
// Portfolio objective over a chosen card set S. Cost is charged ONCE over the
// distinct cards (shared cards are never double-counted).
function portfolioValue(galleries, pools, prices, S, opts) {
  const idOf = x => x.itemId || x.id;
  const chosenIds = new Set(S.map(idOf));
  let value = 0, dTokens = 0, dScore = 0;
  const allCands = [...prices.values()].map(r => r.card);
  for (let i = 0; i < galleries.length; i++) {
    const g = galleries[i], pool = pools[i];
    // Evaluate over (owned pool ∪ all candidates) so bought cards can enter the
    // lineup; the id set selects exactly the owned items plus the chosen cards.
    const universe = pool.concat(allCands);
    const ids = new Set(pool.map(idOf));
    for (const id of chosenIds) if (prices.has(id) && prices.get(id).setIds.has(g.id)) ids.add(id);
    const ev = evalSet(g, universe, ids);
    const b = opts.bases[i];
    const dt = tokens(g, ev.grade) - b.tokens;
    const ds = ev.score - b.score;
    dTokens += dt; dScore += ds;
    value += objectiveValue(opts.objective, dt, ds, 0);
  }
  const totalCost = S.reduce((s, c) => s + loss(c, opts.taxRate), 0);
  return { value, cost: totalCost, dTokens, dScore };
}
// Brute-force reference (used by tests; kept simple so it is obviously correct).
// JSON-friendly signature: (galleries, players, opts) -- builds the world itself.
// Enumerates every subset of size <= maxBundle by COMBINATIONS (not raw bitmasks)
// so that a universe past EXACT_PF_LIMIT (e.g. 24) is still tractable while the
// result is provably exhaustive -- this is what the global B&B path is checked
// against. The hard cap below only guards against absurd universes.
function portfolioBrute(galleries, players, opts) {
  opts = opts || {};
  const w = portfolioWorld(galleries, players, opts);
  const idOf = x => x.itemId || x.id;
  const budget = Math.max(0, (+opts.coins != null ? +opts.coins : Infinity) - (+opts.reserve || 0));
  const vopts = { objective: opts.objective || 'eff', taxRate: opts.taxRate, budget, bases: w.bases };
  let best = [], bestVal = -Infinity, bestCost = 0;
  const cands = w.cands, n = Math.min(cands.length, Math.max(1, +opts.maxBundle || 15));
  if (cands.length > 30) throw new Error('portfolioBrute: candidate universe too large (' + cands.length + ')');
  const rec = (start, S) => {
    const r = portfolioValue(w.gs, w.pools, w.prices, S, vopts);
    if (r.cost <= budget && (r.value > bestVal || (r.value === bestVal && r.cost < bestCost))) {
      bestVal = r.value; best = S.slice(); bestCost = r.cost;
    }
    if (S.length >= n) return;
    for (let i = start; i < cands.length; i++) { S.push(cands[i]); rec(i + 1, S); S.pop(); }
  };
  rec(0, []);
  return { best: best.map(idOf).sort(), value: bestVal, cost: bestCost };
}
// Admissible upper bound for the PORTFOLIO search over the shared card set S.
// value(S) = Σ_g objectiveValue(objective, dt_g, ds_g, 0), where each set's
// realised score is at most its own `setUpperBound` and its cost term is passed
// as 0. Because the objective is monotone in (tokens, score) for every offered
// objective, an upper bound on each set's score (and hence on its Δtokens via
// the grade table) bounds that set's objective term regardless of which cards
// S contains -- so the sum is an upper bound on value(S) for EVERY S. It does
// NOT depend on S, which makes it a (very safe) value-only bound; the budget is
// enforced separately as a hard constraint.
function portfolioUpperBound(galleries, pools, prices, opts) {
  const allCands = [...prices.values()].map(r => r.card);
  let ubVal = 0;
  for (let i = 0; i < galleries.length; i++) {
    const g = galleries[i];
    const universe = pools[i].concat(allCands);
    const ubScore = setUpperBound(g, universe);
    const ubGrade = grade(g, +g.slots || 15, ubScore); // best grade reachable
    const ubTokens = tokens(g, ubGrade);
    const b = opts.bases[i];
    ubVal += objectiveValue(opts.objective, ubTokens - b.tokens, ubScore - b.score, 0);
  }
  return ubVal;
}

// Global Branch & Bound over the SHARED card set S (R3 portfolio path). Nodes are
// subsets of the union candidate universe; the objective is the summed per-set
// objective (cost charged once, at the portfolio level). `maxBundle` caps |S|,
// the post-reserve `budget` is a hard coin constraint, and `maxNodes` caps work.
// Returns { best, value, cost, nodes, aborted, proved, maxNodes }.
function portfolioBranchAndBound(galleries, pools, prices, cands, seed, opts) {
  const idOf = x => x.itemId || x.id;
  const budget = opts.budget;
  const maxBundle = Math.max(1, +opts.maxBundle || 15);
  const maxNodes = +opts.maxNodes > 0 ? +opts.maxNodes : 200000;
  const vopts = { objective: opts.objective, taxRate: opts.taxRate, budget, bases: opts.bases };
  const ubVal = portfolioUpperBound(galleries, pools, prices, vopts);
  // Deterministic order: expensive cards first (bounded early), then by score desc.
  const order = cands.slice().sort((a, b) =>
    (loss(b, opts.taxRate) - loss(a, opts.taxRate)) || (sanScore(b.score) - sanScore(a.score))
    || String(idOf(a)).localeCompare(String(idOf(b))));
  // Seed must itself be affordable, else discard it (B&B returns feasible sets).
  let best = (seed || []).slice();
  const seedCost = best.reduce((s, c) => s + loss(c, opts.taxRate), 0);
  if (seedCost > budget) best = [];
  let bestVal = portfolioValue(galleries, pools, prices, best, vopts).value;
  let bestCost = best.reduce((s, c) => s + loss(c, opts.taxRate), 0);
  let nodes = 0, aborted = false;
  const partialCost = S => S.reduce((s, c) => s + loss(c, opts.taxRate), 0);
  const rec = (idx, S) => {
    if (aborted) return;
    if (++nodes > maxNodes) { aborted = true; return; }
    // Admissible value bound: if even the best possible cannot beat the incumbent,
    // prune. (Cost is a hard constraint, handled below, not in the value bound.)
    if (ubVal <= bestVal) return;
    if (S.length >= maxBundle || idx >= order.length) return;
    for (let i = idx; i < order.length; i++) {
      const c = order[i];
      if (S.some(x => idOf(x) === idOf(c))) continue;
      if (partialCost(S) + loss(c, opts.taxRate) > budget) continue; // hard budget
      const S2 = S.concat([c]);
      const r = portfolioValue(galleries, pools, prices, S2, vopts);
      if (r.value > bestVal || (r.value === bestVal && r.cost < bestCost)) {
        bestVal = r.value; best = S2.slice(); bestCost = r.cost;
      }
      rec(i + 1, S2);
    }
  };
  rec(0, []);
  return { best, value: bestVal, cost: bestCost, nodes, aborted, proved: !aborted, maxNodes };
}

// 2-opt refinement for the portfolio: drop up to two cards, refill from the free
// candidates, keep any edit that raises value within the budget. Deterministic.
function portfolioImprove2opt(galleries, pools, prices, cands, sel, opts) {
  const idOf = x => x.itemId || x.id;
  const budget = opts.budget;
  const vopts = { objective: opts.objective, taxRate: opts.taxRate, budget, bases: opts.bases };
  const spendOf = list => list.reduce((s, c) => s + loss(c, opts.taxRate), 0);
  const valOf = list => portfolioValue(galleries, pools, prices, list, vopts).value;
  let cur = sel.slice(), curVal = valOf(cur);
  for (let pass = 0; pass < 4; pass++) {
    let best = null, bestVal = curVal;
    for (let i = 0; i < cur.length; i++) {
      for (let j = i; j < cur.length; j++) {
        const base = cur.slice(); base.splice(j, 1); if (i !== j) base.splice(i, 1);
        const used = new Set(base.map(idOf));
        for (const c of cands) {
          if (used.has(idOf(c))) continue;
          const cand = base.concat([c]);
          if (spendOf(cand) > budget) continue;
          const v = valOf(cand);
          if (v > bestVal) { bestVal = v; best = cand; }
        }
      }
    }
    if (!best) break;
    cur = best; curVal = bestVal;
  }
  return cur;
}

// Deterministic greedy marginal seed over the shared candidate universe (cost
// charged once). Used ONLY as a B&B seed, so it is also itself a feasible plan.
function portfolioGreedySeed(galleries, pools, prices, cands, opts) {
  const vopts = { objective: opts.objective, taxRate: opts.taxRate, budget: opts.budget, bases: opts.bases };
  let selected = [], selVal = portfolioValue(galleries, pools, prices, selected, vopts).value;
  const usedIds = new Set();
  for (let k = 0; k < Math.max(1, +opts.maxBundle || 15); k++) {
    let bestC = null, bestV = selVal;
    for (const c of cands) {
      const id = c.itemId || c.id;
      if (usedIds.has(id)) continue;
      const trial = selected.concat([c]);
      const r = portfolioValue(galleries, pools, prices, trial, vopts);
      if (r.cost > opts.budget) continue;
      if (r.value > bestV) { bestV = r.value; bestC = c; }
    }
    if (!bestC) break;
    selected.push(bestC); usedIds.add(bestC.itemId || bestC.id); selVal = bestV;
  }
  return selected;
}

// Search a portfolio over the SHARED card set S. The PRIMARY path is a real
// Branch & Bound over S (the same R3 method as `planSet`), seeded by a feasible
// greedy marginal plan and refined by a budget-respecting 2-opt. The post-reserve
// budget `coins - reserve` is a hard constraint; a shared card's loss is charged
// once. `optimality` is reported honestly:
//   'proved'     -> B&B exhausted its search under the admissible bound (node cap
//                   never hit), so the plan is PROVEN optimal.
//   'node_limit' -> the `maxNodes` cap tripped; the plan is the BEST FOUND.
// A very small universe (<= EXACT_PF_LIMIT) is enumerated exhaustively and is
// proven by construction.
const EXACT_PF_LIMIT = 20;
function portfolioPlan(galleries, players, opts) {
  opts = opts || {};
  const objective = opts.objective || 'eff';
  const taxRate = opts.taxRate;
  const coins = +opts.coins != null ? +opts.coins : Infinity;
  const reserve = +opts.reserve || 0;
  const budget = Math.max(0, coins - reserve);
  const maxBundle = Math.max(1, +opts.maxBundle || 15);

  const w = portfolioWorld(galleries, players, opts);
  const gs = w.gs, pools = w.pools, prices = w.prices, cands = w.cands;
  const vopts = { objective, taxRate, budget, bases: w.bases };

  // Per-set detail rows for a chosen id list (shared by every regime).
  const detailFor = chosenIds => gs.map((g, i) => {
    const universe = pools[i].concat(cands);
    const ids = new Set(pools[i].map(x => x.itemId || x.id));
    for (const id of chosenIds) if (prices.has(id) && prices.get(id).setIds.has(g.id)) ids.add(id);
    const ev = evalSet(g, universe, ids);
    return { set: g.id, dScore: ev.score - w.bases[i].score,
      dTokens: tokens(g, ev.grade) - w.bases[i].tokens, newGrade: ev.grade };
  });

  // ---- Tiny-universe regime: exhaustive enumeration (proven by construction).
  if (cands.length <= EXACT_PF_LIMIT) {
    let bestS = [], bestVal = -Infinity, bestCost = 0, nodes = 0;
    for (let mask = 0; mask < (1 << cands.length); mask++) {
      const S = [];
      for (let i = 0; i < cands.length; i++) if (mask & (1 << i)) S.push(cands[i]);
      if (S.length > maxBundle) continue;
      nodes++;
      const r = portfolioValue(gs, pools, prices, S, vopts);
      if (r.cost > budget) continue;
      if (r.value > bestVal || (r.value === bestVal && r.cost < bestCost)) {
        bestVal = r.value; bestS = S; bestCost = r.cost;
      }
    }
    const chosenIds = bestS.map(x => x.itemId || x.id).sort();
    const rr = portfolioValue(gs, pools, prices, bestS, vopts);
    return {
      objective, coins, reserve, budget, universe: cands.length,
      chosen: chosenIds, cost: bestCost, value: rr.value, dTokens: rr.dTokens, dScore: rr.dScore,
      feasible: bestCost <= budget, detail: detailFor(chosenIds),
      optimality: 'proved', proven: true, exact: true, nodes
    };
  }

  // ---- Global B&B over the shared set S (the R3 portfolio path, larger pools).
  const seed = portfolioGreedySeed(gs, pools, prices, cands, { objective, taxRate, budget, maxBundle, bases: w.bases });
  const bb = portfolioBranchAndBound(gs, pools, prices, cands, seed, {
    objective, taxRate, budget, maxBundle, bases: w.bases,
    maxNodes: +opts.maxNodes > 0 ? +opts.maxNodes : 200000
  });
  // 2-opt refinement (budget-respecting): keep it only if it raises value.
  const refined = portfolioImprove2opt(gs, pools, prices, cands, bb.best, { objective, taxRate, budget, bases: w.bases });
  const refinedVal = portfolioValue(gs, pools, prices, refined, vopts).value;
  const chosenSel = refinedVal >= bb.value ? refined : bb.best;
  const chosenIds = chosenSel.map(x => x.itemId || x.id).sort();
  const rr = portfolioValue(gs, pools, prices, chosenSel, vopts);
  const optimality = bb.proved ? 'proved' : 'node_limit';
  return {
    objective, coins, reserve, budget, universe: cands.length,
    chosen: chosenIds, cost: rr.cost, value: rr.value, dTokens: rr.dTokens, dScore: rr.dScore,
    feasible: rr.cost <= budget, detail: detailFor(chosenIds),
    optimality, proven: bb.proved, exact: false, nodes: bb.nodes
  };
}
// Alias kept so existing imports/tests that referenced EXACT_PORTFOLIO_LIMIT
// still resolve (the portfolio now also runs a global B&B beyond that limit).
const EXACT_PORTFOLIO_LIMIT = EXACT_PF_LIMIT;

// Plan every set and rank. `plans` is a deterministic best-first list.
function plan(galleries, players, opts) {
  opts = opts || {};
  const p = (galleries || []).map(g => planSet(g, players, opts));
  const ranked = p.slice().sort((a, b) => (b.value - a.value)
    || (b.dTokens - a.dTokens) || (b.dScore - a.dScore) || String(a.set).localeCompare(String(b.set)));
  const portfolio = portfolioPlan(galleries, players, opts);
  return { plans: ranked, all: p, portfolio };
}
// ===== ENGINE END =====
if (typeof module !== 'undefined' && module.exports) module.exports = { G, TAG, DEFAULT_COUNT_TOP_TAGS, pct, bonus, sanScore, score, lineup, grade, tokens, loss, eligible, norm, evalG, summary, poolFor, candidatesFor, evalSet, evalMemoReset, gain1, objectiveValue, improve2opt, spendTotal, planSet, plan, setUpperBound, bbUpperBound, bbValue, branchAndBound, portfolioWorld, portfolioPlan, portfolioValue, portfolioBrute, portfolioUpperBound, portfolioBranchAndBound, portfolioImprove2opt, portfolioGreedySeed, EXACT_PORTFOLIO_LIMIT };