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

// Core bonus primitive: floor(sum of matched item scores * pct).
// Extracted as a standalone function so unit tests can target it directly.
function bonus(matchedItems, p) {
  if (!p) return 0;
  const sum = matchedItems.reduce((s, x) => s + (+x.score || 0), 0);
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
  const base = items.reduce((s, p) => s + (+p.score || 0), 0);
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
    if (!prev || (+p.score || 0) > (+prev.score || 0)) byId.set(k, p);
  }
  pool = [...byId.values()];
  if (pool.length <= n) return { items: pool.slice(), ...score(pool) };
  const cur = pool.slice().sort((a, b) => b.score - a.score).slice(0, n);
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
// ===== ENGINE END =====
if (typeof module !== 'undefined' && module.exports) module.exports = { G, TAG, DEFAULT_COUNT_TOP_TAGS, pct, bonus, score, lineup, grade, tokens, loss, eligible, norm, evalG, summary };