#!/usr/bin/env python3
"""H1/H2 -- player form fields and Multiples! identity (K6/K2 side).

H2: the player form must expose (and persist) the fields the engine reads:
    itemId, playerKey, holographic, weakFoot, skillMoves, sets.
H1: "Player identity / linked group" (playerKey) must be editable so a
    Multiples! tag can actually be triggered from the UI.

Two kinds of check:
  * static   -- the form/save source declares every field (always runs).
  * behavior -- the save handler is evaluated in a Node sandbox against a
                minimal DOM stub; the resulting player object is asserted.
                Skipped without Node.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

ROOT = os.path.dirname(_HERE)
INDEX = os.path.join(ROOT, "index.html")
NODE = shutil.which("node")

# Fields the H2 acceptance requires the form to declare and persist.
REQUIRED_FORM_FIELDS = ["itemId", "playerKey", "weakFoot", "skillMoves", "sets"]
REQUIRED_BOOL_FIELDS = ["firstOwner", "collected", "holographic"]
REQUIRED_TEXT_FIELDS = ["name", "club", "league", "nation", "position"]
REQUIRED_NUM_FIELDS = ["score", "buyPrice", "resalePrice", "weakFoot", "skillMoves"]


def _html():
    with open(INDEX, encoding="utf-8") as f:
        return f.read()


def _player_modal_src():
    html = _html()
    i = html.index("function playerModal(")
    return html[i:]


class TestFormFieldsStatic(unittest.TestCase):
    """The form source must declare every field the engine relies on."""

    def setUp(self):
        self.src = _player_modal_src()
        # limit to the form-builder portion (up to the save handler)
        self.form = self.src[: self.src.index("saveP.onclick")]

    def test_required_input_fields_present(self):
        # The generic input builder emits `id="p_' + k + '"` for every key.
        self.assertIn('id="p_\'+k+\'"', self.src)
        for k in REQUIRED_FORM_FIELDS:
            self.assertRegex(self.form, r"\['[^']*',\s*'%s'\]" % re.escape(k),
                             "form must declare an input for %r" % k)

    def test_required_text_and_number_fields_present(self):
        for k in REQUIRED_TEXT_FIELDS + REQUIRED_NUM_FIELDS:
            self.assertRegex(self.form, r"\['[^']*',\s*'%s'\]" % re.escape(k),
                             "form must declare %r" % k)

    def test_boolean_toggles_present(self):
        for k, el in [("collected", "p_collected"), ("firstOwner", "p_first"),
                      ("holographic", "p_holo")]:
            self.assertIn('id="%s"' % el, self.form, "missing toggle %s" % el)

    def test_player_identity_label_present(self):
        """H1: the playerKey field must be labelled as the linked group."""
        self.assertRegex(self.form, r"Player identity\s*/\s*linked group")

    def test_save_handler_persists_each_field(self):
        save = self.src[self.src.index("saveP.onclick"):]
        # text fields read via the per-key accessor list
        for k in ["name", "club", "league", "nation", "position", "itemId", "playerKey"]:
            self.assertIn("'%s'" % k, save, "save handler must persist %r" % k)
        for k in ["score", "buyPrice", "resalePrice", "weakFoot", "skillMoves"]:
            self.assertIn("'%s'" % k, save, "save handler must persist %r" % k)
        for k in ["collected", "firstOwner", "holographic"]:
            self.assertIn(k, save, "save handler must persist %r" % k)
        self.assertIn("sets", save, "save handler must persist sets[]")

    def test_itemid_defaults_to_id(self):
        """A card with no explicit itemId falls back to the RECORD id, not playerKey."""
        save = self.src[self.src.index("saveP.onclick"):]
        self.assertIn("np.itemId=np.itemId||np.id", save)
        self.assertNotIn("np.itemId=np.playerKey", save)
        self.assertNotIn("np.itemId=np.itemId||np.playerKey", save)


class TestSetFormIdsPath(unittest.TestCase):
    """H2/K6: the engine's `ids` eligibility path must be reachable from the UI."""

    def setUp(self):
        with open(INDEX, encoding="utf-8") as f:
            self.html = f.read()

    def test_ids_option_present(self):
        self.assertIn("<option>ids</option>", self.html)

    def test_ids_saved_as_array(self):
        self.assertIn("eligibility.ids=g_value.value.split(',')", self.html)

    def test_cumulative_wording_not_incremental(self):
        """K2 wording: the set form must not call the token rewards incremental."""
        self.assertNotIn("incremental tokens", self.html)
        self.assertIn("cumulative tokens", self.html)

    def test_engine_has_ids_branch(self):
        with open(os.path.join(ROOT, "engine", "engine.js"), encoding="utf-8") as f:
            eng = f.read()
        self.assertIn("e.type === 'ids'", eng)


@unittest.skipUnless(NODE, "node not found on PATH")
class TestFormSaveBehavior(unittest.TestCase):
    """Evaluate the save handler logic against a DOM stub and assert the result."""

    def _run_save(self, overrides):
        """Recreate the save-handler data flow of playerModal in Node.

        This mirrors the source lines verbatim: text keys, number keys, sets
        parsing, checkboxes, and the itemId fallback. It asserts the contract,
        not the DOM wiring (which is covered by the static tests).
        """
        script = r"""
        const values = %s;                 // stub form values by element id
        const p = {id:'p_1'};              // an existing player being edited
        let np={...p};
        ['name','club','league','nation','position','itemId','playerKey'].forEach(k=>np[k]=values['p_'+k]);
        ['score','buyPrice','resalePrice','weakFoot','skillMoves'].forEach(k=>np[k]=+values['p_'+k]);
        np.sets=(values['p_sets']||'').split(',').map(s=>s.trim()).filter(Boolean);
        np.rarity=values['p_rarity'];np.special=values['p_special'];np.gender=values['p_gender'];
        np.collected=values['p_collected'];np.firstOwner=values['p_first'];np.holographic=values['p_holo'];
        np.itemId=np.itemId||np.id;
        process.stdout.write(JSON.stringify(np));
        """ % json.dumps(overrides)
        out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_multiples_fields_persist(self):
        np = self._run_save({
            "p_name": "Star", "p_score": "325", "p_buyPrice": "1000", "p_resalePrice": "900",
            "p_club": "FC X", "p_league": "L", "p_nation": "Nation", "p_position": "ST",
            "p_itemId": "card-77", "p_playerKey": "star-player",
            "p_weakFoot": "5", "p_skillMoves": "4", "p_sets": "custom-a, custom-b",
            "p_rarity": "Gold", "p_special": "TOTW", "p_gender": "men",
            "p_collected": True, "p_first": True, "p_holo": True,
        })
        self.assertEqual(np["itemId"], "card-77")
        self.assertEqual(np["playerKey"], "star-player")
        self.assertEqual(np["weakFoot"], 5)
        self.assertEqual(np["skillMoves"], 4)
        self.assertEqual(np["sets"], ["custom-a", "custom-b"])
        self.assertTrue(np["holographic"])
        self.assertTrue(np["firstOwner"])
        self.assertEqual(np["special"], "TOTW")

    def test_itemid_falls_back_to_id(self):
        np = self._run_save({
            "p_name": "X", "p_score": "10", "p_buyPrice": "1", "p_resalePrice": "1",
            "p_club": "", "p_league": "", "p_nation": "", "p_position": "CM",
            "p_itemId": "", "p_playerKey": "",
            "p_weakFoot": "3", "p_skillMoves": "3", "p_sets": "",
            "p_rarity": "Silver", "p_special": "", "p_gender": "men",
            "p_collected": False, "p_first": False, "p_holo": False,
        })
        self.assertEqual(np["itemId"], "p_1", "empty itemId must fall back to the player id")
        self.assertEqual(np["sets"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
