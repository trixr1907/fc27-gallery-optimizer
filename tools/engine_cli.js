#!/usr/bin/env node
/*
 * Engine CLI bridge (dev-time only; no npm packages required).
 *
 * Reads JSON-Lines from stdin: one request object per line, one response per
 * line. This lets the Python unittest suite exercise the REAL engine without
 * spawning a Node process per assertion.
 *
 * Request:  {"fn": "score", "args": [ {items}, {"countTopTags": 10} ]}
 *           {"fn": "bonus", "args": [ [ {score:10} ], 0.02 ]}
 * Response: {"ok": true, "result": ...}
 *        or {"ok": false, "error": "..."}
 *
 * Special: {"fn": "__ping__"} -> {"ok": true, "exports": [...]}
 */
const path = require('path');
const eng = require(path.join(__dirname, '..', 'engine', 'engine.js'));

const FN = {
  pct: eng.pct,
  bonus: eng.bonus,
  score: eng.score,
  lineup: eng.lineup,
  grade: eng.grade,
  tokens: eng.tokens,
  loss: eng.loss,
  eligible: eng.eligible,
  norm: eng.norm,
  evalG: eng.evalG,
  summary: eng.summary,
  poolFor: eng.poolFor,
  candidatesFor: eng.candidatesFor,
  evalSet: eng.evalSet,
  evalMemoReset: () => { eng.evalMemoReset(); return true; },
  gain1: eng.gain1,
  objectiveValue: eng.objectiveValue,
  improve2opt: eng.improve2opt,
  spendTotal: eng.spendTotal,
  planSet: (g, players, opts) => eng.planSet(g, players, opts),
  plan: (galleries, players, opts) => eng.plan(galleries, players, opts),
  setUpperBound: eng.setUpperBound,
  bbUpperBound: eng.bbUpperBound,
  bbValue: eng.bbValue,
  branchAndBound: eng.branchAndBound,
  portfolioPlan: (galleries, players, opts) => eng.portfolioPlan(galleries, players, opts),
  portfolioBrute: (galleries, players, opts) => eng.portfolioBrute(galleries, players, opts),
  portfolioWorld: (galleries, players, opts) => {
    const w = eng.portfolioWorld(galleries, players, opts || {});
    // Return a JSON-friendly view: drop the Map/Set containers but expose the
    // candidate cards, per-set pools/bases and each card's eligible setIds.
    const prices = {};
    for (const [id, rec] of w.prices) prices[id] = { card: rec.card, setIds: [...rec.setIds] };
    return { pools: w.pools, bases: w.bases, prices, cands: w.cands };
  },
  portfolioValue: (galleries, players, opts, ids) => {
    const w = eng.portfolioWorld(galleries, players, opts || {});
    const idSet = new Set(ids || []);
    const S = w.cands.filter(c => idSet.has(c.itemId || c.id));
    const budget = Math.max(0, (+(opts && opts.coins != null ? opts.coins : Infinity)) - (+(opts && opts.reserve) || 0));
    return eng.portfolioValue(w.gs, w.pools, w.prices, S, { objective: (opts && opts.objective) || 'eff', taxRate: opts && opts.taxRate, budget, bases: w.bases });
  },
  portfolioUpperBound: (galleries, players, opts) => {
    const w = eng.portfolioWorld(galleries, players, opts || {});
    return eng.portfolioUpperBound(w.gs, w.pools, w.prices, Object.assign({ bases: w.bases }, opts || {}));
  },
  sanScore: eng.sanScore,
  TAG: () => eng.TAG
};

function handle(req) {
  if (!req || typeof req !== 'object') throw new Error('request must be an object');
  if (req.fn === '__ping__') return { exports: Object.keys(eng) };
  const fn = FN[req.fn];
  if (typeof fn !== 'function') throw new Error('unknown fn: ' + req.fn);
  let args = Array.isArray(req.args) ? req.args.slice() : [];
  // JSON has no Set: engine functions taking an `idSet`/`collectedIds` Set get
  // an array over the wire -- coerce by parameter position.
  if (req.fn === 'evalSet' && Array.isArray(args[2])) args[2] = new Set(args[2]);
  if (req.fn === 'planSet' && args[2] && Array.isArray(args[2].collectedIds)) args[2] = Object.assign({}, args[2], { collectedIds: new Set(args[2].collectedIds) });
  if (req.fn === 'plan' && args[2] && Array.isArray(args[2].collectedIds)) args[2] = Object.assign({}, args[2], { collectedIds: new Set(args[2].collectedIds) });
  if (req.fn === 'portfolioPlan' && args[2] && Array.isArray(args[2].collectedIds)) args[2] = Object.assign({}, args[2], { collectedIds: new Set(args[2].collectedIds) });
  if (req.fn === 'portfolioBrute' && args[2] && Array.isArray(args[2].collectedIds)) args[2] = Object.assign({}, args[2], { collectedIds: new Set(args[2].collectedIds) });
  if (req.fn === 'portfolioUpperBound' && args[2] && Array.isArray(args[2].collectedIds)) args[2] = Object.assign({}, args[2], { collectedIds: new Set(args[2].collectedIds) });
  if (req.fn === 'portfolioWorld' && args[2] && Array.isArray(args[2].collectedIds)) args[2] = Object.assign({}, args[2], { collectedIds: new Set(args[2].collectedIds) });
  if (req.fn === 'portfolioValue' && args[2] && Array.isArray(args[2].collectedIds)) args[2] = Object.assign({}, args[2], { collectedIds: new Set(args[2].collectedIds) });
  if (req.fn === 'poolFor' && Array.isArray(args[2])) args[2] = new Set(args[2]);
  if (req.fn === 'candidatesFor' && Array.isArray(args[2])) args[2] = new Set(args[2]);
  return fn.apply(null, args);
}

let buf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => {
  buf += chunk;
  let nl;
  while ((nl = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, nl).trim();
    buf = buf.slice(nl + 1);
    if (!line) continue;
    let out;
    try {
      const req = JSON.parse(line);
      out = { ok: true, result: handle(req) };
    } catch (e) {
      out = { ok: false, error: String(e && e.message ? e.message : e) };
    }
    process.stdout.write(JSON.stringify(out) + '\n');
  }
});
process.stdin.on('end', () => {
  const line = buf.trim();
  if (line) {
    let out;
    try {
      out = { ok: true, result: handle(JSON.parse(line)) };
    } catch (e) {
      out = { ok: false, error: String(e && e.message ? e.message : e) };
    }
    process.stdout.write(JSON.stringify(out) + '\n');
  }
});
