#!/usr/bin/env python3
"""P2 -- UI-side state schema + dated price snapshots (behaviour, not presence).

The server-side P2 modules (alias, cache, prices, schema migration, hardening)
are proven separately in their own modules. This file proves the OTHER half of
the same contract: the browser UI in index.html must (a) treat prices as DATED
SNAPSHOTS, (b) migrate a saved state forward on load/import, and (c) feed the
REAL engine such that a snapshot price yields exactly the same plan as the bare
number it wraps.

Method (mirrors TestGlobalPortfolioUiBehavior in test_plan.py): we extract the
verbatim UI functions from index.html by regex and evaluate them in one Node
scope that also `require()`s the REAL engine. We never re-implement the UI logic
in Python -- we run the shipped source and assert behaviour.
"""

import json
import os
import re
import subprocess
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = os.environ.get("NODE", "node")


def _extract(html, pattern, label):
    m = re.search(pattern, html, re.S)
    if not m:
        raise AssertionError("could not extract %s from index.html" % label)
    return m.group(0)


class UiSchemaTestCase(unittest.TestCase):
    """Shared loader: pull the UI schema block out of the shipped index.html and
    run it in Node together with the real engine."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(_ROOT, "index.html"), encoding="utf-8") as f:
            cls.html = f.read()

    def _ui_schema_block(self):
        """The whole UI schema layer: from `const SCHEMA_VERSION=` up to the first
        DOM-bound wrapper (`const loss0=`). Everything in it is pure/injectable,
        so it runs verbatim in Node with a stubbed localStorage."""
        start = self.html.index("const SCHEMA_VERSION=")
        end = self.html.index("const loss0=", start)
        return self.html[start:end]

    def _run(self, body, storage_preload=None):
        engine = os.path.join(_ROOT, "engine", "engine.js")
        script = (
            "const M = require(%s);\n"
            "Object.assign(globalThis, M);\n"
            % json.dumps(engine.replace("\\", "/"))
        )
        # A minimal localStorage stub so the real loadFrom/saveTo can run headless.
        preload = list((storage_preload or {}).items())
        script += (
            "const __store = new Map(%s);\n"
            "const localStorage = { getItem:(k)=>__store.has(k)?__store.get(k):null,\n"
            "  setItem:(k,v)=>__store.set(k,String(v)), removeItem:(k)=>__store.delete(k),\n"
            "  _dump:()=>Object.fromEntries(__store) };\n"
            % json.dumps(preload)
        )
        # The real shipped UI code, copied verbatim (source of truth = index.html).
        script += self._ui_schema_block()
        script += "\n"
        script += body
        out = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                             timeout=60, cwd=_ROOT)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)
        script += body
        out = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                             timeout=60, cwd=_ROOT)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)


class TestPriceSnapshot(UiSchemaTestCase):
    def test_bare_number_is_wrapped_with_a_stamp(self):
        body = r"""
        const s = priceSnapshot(1234);
        process.stdout.write(JSON.stringify({v:s.value, hasStamp: !!s.fetchedAt,
          iso: /^\d{4}-\d{2}-\d{2}T/.test(s.fetchedAt)}));
        """
        r = self._run(body)
        self.assertEqual(r["v"], 1234)
        self.assertTrue(r["hasStamp"])
        self.assertTrue(r["iso"])

    def test_numeric_string_is_accepted(self):
        r = self._run("process.stdout.write(JSON.stringify(priceSnapshot('42')));")
        self.assertEqual(r["value"], 42)

    def test_missing_or_invalid_is_null(self):
        body = r"""
        process.stdout.write(JSON.stringify([
          priceSnapshot(null), priceSnapshot(''), priceSnapshot('abc'), priceSnapshot(NaN)
        ]));
        """
        r = self._run(body)
        self.assertEqual(r, [None, None, None, None])

    def test_existing_snapshot_is_preserved_keeps_its_stamp(self):
        body = r"""
        const orig = { value: 900, fetchedAt: '2026-01-02T00:00:00.000Z', source: 'fut.gg' };
        const s = priceSnapshot(orig, '2030-01-01T00:00:00.000Z');
        process.stdout.write(JSON.stringify({v:s.value, stamp:s.fetchedAt, src:s.source}));
        """
        r = self._run(body)
        self.assertEqual(r["v"], 900)
        self.assertEqual(r["stamp"], "2026-01-02T00:00:00.000Z",
                         "an existing date must NOT be overwritten by the migration")
        self.assertEqual(r["src"], "fut.gg")

    def test_snapshot_without_stamp_gets_the_injected_one(self):
        body = r"""
        const s = priceSnapshot({ value: 5 }, '2030-01-01T00:00:00.000Z');
        process.stdout.write(JSON.stringify({v:s.value, stamp:s.fetchedAt}));
        """
        r = self._run(body)
        self.assertEqual(r["stamp"], "2030-01-01T00:00:00.000Z")

    def test_priceValue_reads_both_shapes(self):
        body = r"""
        process.stdout.write(JSON.stringify([
          priceValue(7), priceValue('8'), priceValue({value:9}), priceValue(null)
        ]));
        """
        r = self._run(body)
        self.assertEqual(r, [7, "8", 9, None])


class TestMigrateState(UiSchemaTestCase):
    def _legacy_state(self):
        return r"""
        const legacy = { players: [
            { id:'p1', itemId:'p1', name:'A', score:100, buyPrice:1200, resalePrice:900 },
            { id:'p2', itemId:'p2', name:'B', score:100 }
        ], galleries: [ { id:'g1', name:'G', sourceUrl:'https://www.fut.gg/fut-gallery/x/' } ] };
        """

    def test_v1_bare_prices_become_snapshots(self):
        body = self._legacy_state() + r"""
        const m = migrateState(legacy);
        const p1 = m.players[0];
        process.stdout.write(JSON.stringify({
          schema: m.schemaVersion,
          buyIsObj: p1.buyPrice && typeof p1.buyPrice === 'object',
          buyVal: p1.buyPrice.value, resaleVal: p1.resalePrice.value,
          stamped: !!p1.buyPrice.fetchedAt && !!p1.priceFetchedAt
        }));
        """
        r = self._run(body)
        self.assertEqual(r["schema"], 2)
        self.assertTrue(r["buyIsObj"])
        self.assertEqual(r["buyVal"], 1200)
        self.assertEqual(r["resaleVal"], 900)
        self.assertTrue(r["stamped"])

    def test_price_less_player_is_left_untouched(self):
        body = self._legacy_state() + r"""
        const m = migrateState(legacy);
        const p2 = m.players[1];
        process.stdout.write(JSON.stringify({
          hasBuy: 'buyPrice' in p2, hasStamp: 'priceFetchedAt' in p2
        }));
        """
        r = self._run(body)
        self.assertFalse(r["hasBuy"], "a player without a price must not gain one")
        self.assertFalse(r["hasStamp"])

    def test_gallery_sourceUrl_gains_fetchedAt(self):
        body = self._legacy_state() + r"""
        const m = migrateState(legacy);
        process.stdout.write(JSON.stringify({ stamp: !!m.galleries[0].fetchedAt }));
        """
        r = self._run(body)
        self.assertTrue(r["stamp"])

    def test_already_current_state_is_not_re_wrapped(self):
        body = self._legacy_state() + r"""
        const once = migrateState(legacy);
        const twice = migrateState(once);
        process.stdout.write(JSON.stringify({
          sameVal: twice.players[0].buyPrice.value,
          stampKept: twice.players[0].buyPrice.fetchedAt === once.players[0].buyPrice.fetchedAt
        }));
        """
        r = self._run(body)
        self.assertEqual(r["sameVal"], 1200)
        self.assertTrue(r["stampKept"], "migration must be idempotent")

    def test_newer_schema_is_rejected(self):
        body = r"""
        let msg = 'NO_THROW';
        try { migrateState({ schemaVersion: 99, players: [], galleries: [] }); }
        catch (e) { msg = e.message; }
        process.stdout.write(JSON.stringify({ msg }));
        """
        r = self._run(body)
        self.assertIn("newer", r["msg"])


class TestEngineAcceptsSnapshots(UiSchemaTestCase):
    """The whole point of `priceOf`: a plan computed from snapshot prices must be
    IDENTICAL to the plan computed from the bare numbers those snapshots wrap."""

    def _scenario(self):
        return r"""
        const mk=(id,score,buy,resale,o={})=>Object.assign({id,itemId:id,playerKey:id,name:id,score,
          club:'AC',position:'CM',nation:'Spain',league:'L',rarity:'',special:'',collected:false,
          buyPrice:buy,resalePrice:resale},o);
        function scenario(priceWrap){
          return { settings:{objective:'eff',taxRate:.05,maxBundle:5,coins:1000000000,reserve:0},
            players:[
              mk('o0',110,0,0,{collected:true}), mk('o1',100,0,0,{collected:true}),
              mk('a',260,1200,1140), mk('b',240,800,760), mk('c',300,1500,1425)
            ].map(p=>Object.assign({},p,
              ('buyPrice' in p && priceWrap) ? {buyPrice:priceWrap(p.buyPrice), resalePrice:priceWrap(p.resalePrice)} : {})),
            galleries:[
              {id:'g1',name:'g1',slots:4,eligibility:{type:'club',value:'AC'},
               thresholds:{D:10,C:400,B:800,A:1200,S:1600}, rewards:{D:0,C:5,B:12,A:24,S:48}}
            ] };
        }
        """

    def _plan(self, price_wrap_expr):
        body = self._scenario() + r"""
        const st = scenario(%s);
        evalMemoReset();
        const p = planSet(st.galleries[0], st.players,
          { objective:'eff', taxRate:.05, maxBundle:5, coins:1000000000 });
        process.stdout.write(JSON.stringify({
          chosen: p.chosen.slice().sort(), loss: p.loss, dScore: p.dScore, dTokens: p.dTokens
        }));
        """ % price_wrap_expr
        return self._run(body)

    def test_snapshot_prices_give_identical_plan(self):
        bare = self._plan("null")
        wrapped = self._plan("(v)=>priceSnapshot(v,'2026-01-02T00:00:00.000Z')")
        self.assertEqual(bare["chosen"], wrapped["chosen"],
                         "snapshot vs bare prices must select the same cards")
        self.assertEqual(bare["loss"], wrapped["loss"],
                         "loss must be read through priceOf identically")
        self.assertEqual(bare["dScore"], wrapped["dScore"])

    def test_bare_plan_is_non_trivial(self):
        bare = self._plan("null")
        # A sanity anchor so the previous test cannot pass vacuously.
        self.assertTrue(bare["chosen"], "the scenario must produce a real plan")


class TestPriceScenarioAffectsPlan(UiSchemaTestCase):
    """The decisive P2.10 test the review asked for: a PRICE CHANGE must move the
    economics (loss / feasibility / ranking), while a METADATA-ONLY change (a new
    timestamp, same numbers) must NOT change any score. This proves `priceOf`
    actually feeds cost/budget/objective -- not merely that it parses two shapes.
    """

    def _run_engine(self, body):
        return self._run(body)

    def _scenario(self, *, price_expr):
        # Two candidates at the SAME score, different loss. Which one is bought
        # (and whether a purchase is affordable at all) must depend on price.
        return r"""
        const mk=(id,score,o={})=>Object.assign({id,itemId:id,playerKey:id,name:id,score,
          club:'AC',position:'CM',nation:'Spain',league:'L',rarity:'',special:'',collected:false},o);
        const st = { settings:{objective:'eff',taxRate:.05,maxBundle:5,coins:COINS,reserve:0},
          players:[
            mk('o0',110,{collected:true}), mk('o1',100,{collected:true}),
            mk('cheap',300,{buyPrice:100,resalePrice:100}),
            mk('pricey',300,{buyPrice:900,resalePrice:900})
          ],
          galleries:[{id:'g1',name:'g1',slots:4,eligibility:{type:'club',value:'AC'},
            thresholds:{D:10,C:400,B:800,A:1200,S:1600}, rewards:{D:0,C:5,B:12,A:24,S:48}}] };
        const priceOf2=(x,sc)=>priceOf(x,sc);
        function run(){
          evalMemoReset();
          return planSet(st.galleries[0], st.players,
            { objective:'eff', taxRate:.05, maxBundle:5, coins:COINS, priceScenario:SCENARIO });
        }
        """

    def test_loss_reflects_the_price_change(self):
        # Same card, two buy prices -> loss must differ by exactly the delta.
        body = r"""
        const card=(buy)=>({buyPrice:buy,resalePrice:buy});
        process.stdout.write(JSON.stringify({
          lossCheap: loss(card(100), .05),
          lossPricey: loss(card(900), .05)
        }));
        """
        r = self._run_engine(body)
        self.assertEqual(r["lossCheap"], 100 - 95)     # 100 - floor(100*0.95)
        self.assertEqual(r["lossPricey"], 900 - 855)   # 900 - floor(900*0.95)
        self.assertNotEqual(r["lossCheap"], r["lossPricey"],
                            "a price change must change the expected loss")

    def test_price_change_changes_ranking_under_budget(self):
        # Both cards score the same; only the cheap one fits a tight budget.
        body = r"""
        const mk=(id,score,o={})=>Object.assign({id,itemId:id,playerKey:id,name:id,score,
          club:'AC',position:'CM',nation:'Spain',league:'L',rarity:'',special:'',collected:false},o);
        function run(coins){
          const players=[mk('o0',110,{collected:true}), mk('o1',100,{collected:true}),
            mk('cheap',300,{buyPrice:100,resalePrice:100}),
            mk('pricey',300,{buyPrice:900,resalePrice:900})];
          const g={id:'g1',name:'g1',slots:4,eligibility:{type:'club',value:'AC'},
            thresholds:{D:10,C:400,B:800,A:1200,S:1600}, rewards:{D:0,C:5,B:12,A:24,S:48}};
          evalMemoReset();
          const p=planSet(g, players, {objective:'eff',taxRate:.05,maxBundle:5,coins});
          return {chosen:p.chosen.slice().sort(), feasible:p.feasible, loss:p.loss};
        }
        process.stdout.write(JSON.stringify({ tight: run(200), loose: run(10_000_000) }));
        """
        r = self._run_engine(body)
        self.assertIn("cheap", r["tight"]["chosen"],
                      "with a tight budget only the cheap card is affordable")
        self.assertNotIn("pricey", r["tight"]["chosen"])
        self.assertLessEqual(r["tight"]["loss"], 200)
        # With a loose budget the pricey card becomes affordable and is chosen.
        self.assertIn("pricey", r["loose"]["chosen"],
                      "raising the budget must admit the pricey card")

    def test_worst_case_scenario_raises_cost_and_can_break_feasibility(self):
        # One card with a scenario spread. Under 'worst' it costs more, so a
        # budget that fit the base price no longer fits the worst-case price.
        body = r"""
        const card={id:'c',itemId:'c',playerKey:'c',name:'c',score:300,
          club:'AC',position:'CM',nation:'Spain',league:'L',rarity:'',special:'',collected:false,
          buyPrice:{value:100,best:80,worst:250,priceUpdatedAt:'2026-10-05T00:00:00Z'},
          resalePrice:{value:100,best:100,worst:80}};
        const o0={id:'o0',itemId:'o0',playerKey:'o0',name:'o0',score:110,club:'AC',position:'CM',
          nation:'Spain',league:'L',rarity:'',special:'',collected:true};
        const g={id:'g1',name:'g1',slots:4,eligibility:{type:'club',value:'AC'},
          thresholds:{D:10,C:400,B:800,A:1200,S:1600}, rewards:{D:0,C:5,B:12,A:24,S:48}};
        function run(sc){ evalMemoReset();
          return planSet(g,[o0,card],{objective:'eff',taxRate:.05,maxBundle:5,coins:150,priceScenario:sc}); }
        const base=run('base'), worst=run('worst'), best=run('best');
        process.stdout.write(JSON.stringify({
          baseChosen: base.chosen.slice().sort(), worstChosen: worst.chosen.slice().sort(),
          bestChosen: best.chosen.slice().sort(),
          baseLoss: loss(card,.05,'base'), worstLoss: loss(card,.05,'worst'), bestLoss: loss(card,.05,'best')
        }));
        """
        r = self._run_engine(body)
        self.assertLess(r["bestLoss"], r["baseLoss"], "best-case loss must be lower")
        self.assertGreater(r["worstLoss"], r["baseLoss"], "worst-case loss must be higher")
        # 150 budget fits base (100) but a 250 worst-case buy must not fit.
        self.assertIn("c", r["baseChosen"])
        self.assertNotIn("c", r["worstChosen"],
                         "the worst-case price must break feasibility under the same budget")

    def test_metadata_only_change_does_not_alter_scores(self):
        # Same numbers, different timestamp: scores MUST be byte-identical.
        body = r"""
        const mk=(id,score,o={})=>Object.assign({id,itemId:id,playerKey:id,name:id,score,
          club:'AC',position:'CM',nation:'Spain',league:'L',rarity:'',special:'',collected:false},o);
        const g={id:'g1',name:'g1',slots:4,eligibility:{type:'club',value:'AC'},
          thresholds:{D:10,C:400,B:800,A:1200,S:1600}, rewards:{D:0,C:5,B:12,A:24,S:48}};
        function run(stamp){
          const players=[mk('o0',110,{collected:true}), mk('o1',100,{collected:true}),
            mk('a',260,{buyPrice:{value:1200,priceUpdatedAt:stamp,source:'fut.gg'},
                        resalePrice:{value:1140,priceUpdatedAt:stamp,source:'fut.gg'}}),
            mk('b',240,{buyPrice:{value:800,priceUpdatedAt:stamp,source:'manual'},
                        resalePrice:{value:760,priceUpdatedAt:stamp,source:'manual'}})];
          evalMemoReset();
          const p=planSet(g, players, {objective:'eff',taxRate:.05,maxBundle:5,coins:1000000000});
          return {chosen:p.chosen.slice().sort(), loss:p.loss, dScore:p.dScore, dTokens:p.dTokens};
        }
        const oldStamp=run('2020-01-01T00:00:00Z'), newStamp=run('2026-10-05T00:00:00Z');
        process.stdout.write(JSON.stringify({ oldStamp, newStamp }));
        """
        r = self._run_engine(body)
        self.assertEqual(r["oldStamp"], r["newStamp"],
                         "changing only the snapshot timestamp/source must not "
                         "change the chosen cards, loss, score or tokens")


class TestPersistenceVersionedKey(UiSchemaTestCase):
    """P2.9: the storage key is versioned and the legacy payload is backed up."""

    def test_legacy_key_is_backed_up_and_migrated(self):
        legacy = json.dumps({"players": [{"id": "p1", "score": 10, "buyPrice": 500}],
                             "galleries": []})
        r = self._run(
            "const res = loadFrom(localStorage);\n"
            "process.stdout.write(JSON.stringify({state:res.state, dump:localStorage._dump()}));",
            storage_preload={"fc27gallery": legacy},
        )
        # v0 payload preserved under the backup key.
        self.assertIn("fc27gallery.v0.bak", r["dump"])
        self.assertEqual(json.loads(r["dump"]["fc27gallery.v0.bak"])["players"][0]["id"], "p1")
        # Migrated state is on schema v2 and the price is a dated snapshot.
        self.assertEqual(r["state"]["schemaVersion"], 2)
        self.assertEqual(r["state"]["players"][0]["buyPrice"]["value"], 500)

    def test_versioned_key_takes_precedence(self):
        v2 = json.dumps({"schemaVersion": 2, "players": [{"id": "new"}], "galleries": []})
        r = self._run(
            "const res = loadFrom(localStorage);\n"
            "process.stdout.write(JSON.stringify({ids:res.state.players.map(p=>p.id)}));",
            storage_preload={"fc27gallery": json.dumps({"players": [{"id": "old"}], "galleries": []}),
                             "fc27gallery.v2": v2},
        )
        self.assertEqual(r["ids"], ["new"])

    def test_save_writes_versioned_key_and_reports_size(self):
        r = self._run(
            "const r = saveTo(localStorage, {schemaVersion:2, players:[], galleries:[]});\n"
            "process.stdout.write(JSON.stringify({ok:r.ok, bytes:r.bytes, warn:r.warn, dump:localStorage._dump()}));",
        )
        self.assertTrue(r["ok"])
        self.assertGreater(r["bytes"], 0)
        self.assertFalse(r["warn"])
        self.assertIn("fc27gallery.v2", r["dump"])

    def test_size_warning_fires_near_4mb(self):
        # A payload just over the 4 MB threshold must set warn=true (non-blocking).
        r = self._run(
            "const big = {schemaVersion:2, players:[{id:'x', pad:'y'.repeat(%d)}], galleries:[]};\n"
            "const r = saveTo(localStorage, big);\n"
            "process.stdout.write(JSON.stringify({warn:r.warn, ok:r.ok}));" % (4 * 1024 * 1024 + 100),
        )
        self.assertTrue(r["warn"], "an oversized payload must trigger the size warning")
        self.assertTrue(r["ok"], "the size warning must not block the save")


class TestUiPriceScenario(UiSchemaTestCase):
    """P2.10 UI mirrors: scenario resolution + staleness, in the shipped code."""

    def test_scenarioOf_reads_spread(self):
        body = r"""
        const snap = {value:100, best:80, worst:250};
        process.stdout.write(JSON.stringify({
          base: scenarioOf(snap,'base'), best: scenarioOf(snap,'best'),
          worst: scenarioOf(snap,'worst'), bare: scenarioOf(42,'worst')
        }));
        """
        r = self._run(body)
        self.assertEqual(r, {"base": 100, "best": 80, "worst": 250, "bare": 42})

    def test_priceStale_detects_old_snapshot(self):
        body = r"""
        const old = {value:1, priceUpdatedAt:'2020-01-01T00:00:00Z'};
        const fresh = {value:1, priceUpdatedAt:'2026-10-04T00:00:00Z'};
        process.stdout.write(JSON.stringify({
          old: priceStale(old, '2026-10-05T00:00:00Z'),
          fresh: priceStale(fresh, '2026-10-05T00:00:00Z'),
          bare: priceStale(5, '2026-10-05T00:00:00Z')
        }));
        """
        r = self._run(body)
        self.assertTrue(r["old"])
        self.assertFalse(r["fresh"])
        self.assertFalse(r["bare"])

    def test_updatedAt_falls_back_to_fetchedat(self):
        body = r"""
        process.stdout.write(JSON.stringify({
          a: priceUpdatedAt({priceUpdatedAt:'T'}), b: priceUpdatedAt({fetchedAt:'O'}),
          c: priceUpdatedAt(5)
        }));
        """
        r = self._run(body)
        self.assertEqual(r, {"a": "T", "b": "O", "c": None})


class TestUiMergePreview(UiSchemaTestCase):
    """P2.8 UI mirror: preview/diff, provenance, manual guard."""

    def test_preview_is_pure_and_classifies(self):
        body = r"""
        const cur = {players:[{id:'p1',score:100,buyPrice:500},{id:'p2',score:250,buyPrice:900}],galleries:[]};
        const inc = {players:[{id:'p1',score:100,buyPrice:500},{id:'p2',score:260,buyPrice:900},{id:'p3',score:50}],galleries:[]};
        const before = JSON.stringify(cur);
        const prev = mergePreview(cur, inc, 'fut.gg');
        const byId = Object.fromEntries(prev.players.map(e=>[e.id,e]));
        process.stdout.write(JSON.stringify({
          unchanged: JSON.stringify(cur)===before,
          p1: byId.p1.status, p2: byId.p2.status, p3: byId.p3.status,
          p2fields: byId.p2.changes.map(c=>c.field),
          summary: prev.summary
        }));
        """
        r = self._run(body)
        self.assertTrue(r["unchanged"], "mergePreview must not mutate its input")
        self.assertEqual(r["p1"], "unchanged")
        self.assertEqual(r["p2"], "changed")
        self.assertEqual(r["p3"], "added")
        self.assertEqual(r["p2fields"], ["score"])
        self.assertEqual(r["summary"]["playersAdded"], 1)
        self.assertEqual(r["summary"]["playersChanged"], 1)

    def test_manual_edit_is_guarded(self):
        body = r"""
        const cur = {players:[{id:'p2',score:250,buyPrice:900}],galleries:[]};
        const inc = {players:[{id:'p2',buyPrice:1000}],galleries:[]};
        const prev = mergePreview(cur, inc, 'fut.gg');
        process.stdout.write(JSON.stringify({
          needs: prev.players[0].needsConfirmation, summary: prev.summary.needsConfirmation
        }));
        """
        r = self._run(body)
        self.assertTrue(r["needs"], "overwriting a hand-edited price must be flagged")
        self.assertTrue(r["summary"])

    def test_provenance_verified_vs_estimated(self):
        body = r"""
        const a = mergePreview({}, {players:[{id:'x'}],galleries:[]}, 'fut.gg');
        const b = mergePreview({}, {players:[{id:'x'}],galleries:[]}, 'json');
        const c = mergePreview({}, {galleries:[{id:'g',slotsEstimated:true}]}, 'fut.gg');
        process.stdout.write(JSON.stringify({
          verified: a.players[0].provenance, estimated: b.players[0].provenance,
          forced: c.galleries[0].provenance
        }));
        """
        r = self._run(body)
        self.assertEqual(r["verified"], "verified")
        self.assertEqual(r["estimated"], "estimated")
        self.assertEqual(r["forced"], "estimated")


if __name__ == "__main__":
    unittest.main(verbosity=2)
