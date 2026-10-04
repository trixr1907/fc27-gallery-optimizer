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
  TAG: () => eng.TAG
};

function handle(req) {
  if (!req || typeof req !== 'object') throw new Error('request must be an object');
  if (req.fn === '__ping__') return { exports: Object.keys(eng) };
  const fn = FN[req.fn];
  if (typeof fn !== 'function') throw new Error('unknown fn: ' + req.fn);
  const args = Array.isArray(req.args) ? req.args : [];
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
