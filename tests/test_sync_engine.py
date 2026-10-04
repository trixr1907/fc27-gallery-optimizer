#!/usr/bin/env python3
"""F5 -- engine sync guard.

Two independent checks, deliberately separated so the sync protection stays
active even on a machine without Node:

  * test_bytes_equal  -- pure Python byte comparison of the marked engine block
                         in index.html against engine/engine.js. ALWAYS runs.
  * test_loadable     -- require('./engine/engine.js') resolves and exports the
                         expected functions. Skipped (not failed) without Node.

The direction is fixed: index.html is the single source of truth, engine/engine.js
is its byte-identical mirror. The compared block MUST include the guarded
module.exports line (the earlier off-by-one bug omitted it).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "tools"))

import sync_engine  # noqa: E402  (tools/sync_engine.py)

INDEX = os.path.join(ROOT, "index.html")
MIRROR = os.path.join(ROOT, "engine", "engine.js")

# Functions the engine block must export (P0 Sorgfaltspflicht: bonus included).
EXPECTED_EXPORTS = {
    "G", "TAG", "DEFAULT_COUNT_TOP_TAGS", "pct", "bonus", "score", "lineup",
    "grade", "tokens", "loss", "eligible", "norm", "evalG", "summary",
}
EXPORT_LINE = "module.exports"


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


class TestEngineSync(unittest.TestCase):
    """Byte-level sync between index.html (source) and engine/engine.js (mirror)."""

    @classmethod
    def setUpClass(cls):
        cls.html = _read(INDEX)
        cls.mirror = _read(MIRROR)
        cls.block = sync_engine.extract_block(cls.html)

    def test_bytes_equal(self):
        """The marked block must be byte-identical to the mirror. Always runs."""
        self.assertEqual(
            self.block, self.mirror,
            "engine drift: engine/engine.js is not byte-identical to the "
            "marked engine block in index.html. Run: python tools/sync_engine.py",
        )
        self.assertEqual(
            hashlib.md5(self.block.encode("utf-8")).hexdigest(),
            hashlib.md5(self.mirror.encode("utf-8")).hexdigest(),
        )

    def test_exports_line_included_in_block(self):
        """Guard against the off-by-one bug: exports line MUST be part of the block."""
        self.assertIn(EXPORT_LINE, self.block,
                      "the compared block must include the guarded module.exports line")
        last = self.block.rstrip("\n").splitlines()[-1]
        # The guarded line begins with `if (typeof module ...` and ends with the
        # module.exports assignment; both must be present on the final line.
        self.assertIn(EXPORT_LINE, last,
                      "block must END on the guarded module.exports line, got: %r" % last)
        self.assertTrue(last.strip().startswith("if"),
                        "exports line must be the guarded `if (typeof module ...)` form")
        self.assertIn("bonus", last, "bonus must be in the exported set")

    def test_markers_single_and_ordered(self):
        """Exactly one START/END pair, in order, and START precedes the exports line."""
        self.assertEqual(self.html.count("// ===== ENGINE START ====="), 1)
        self.assertEqual(self.html.count("// ===== ENGINE END ====="), 1)
        self.assertLess(self.html.index("// ===== ENGINE START ====="),
                        self.html.index("// ===== ENGINE END ====="))

    def test_block_is_side_effect_free(self):
        """The engine block must not touch the DOM, localStorage or a global state."""
        import re as _re
        # Strip comments first: the block's own header comment legitimately
        # mentions these names ("must NOT touch the DOM, localStorage, ...").
        code = _re.sub(r"//[^\n]*", "", self.block)
        code = _re.sub(r"/\*.*?\*/", "", code, flags=_re.S)
        for forbidden in ("document.", "localStorage", "window.", "state."):
            self.assertNotIn(forbidden, code,
                             "engine block must be side-effect free; found %r" % forbidden)


@unittest.skipUnless(shutil.which("node"), "node not found on PATH")
class TestEngineLoadable(unittest.TestCase):
    """require('./engine/engine.js') must resolve and export the full API."""

    def test_loadable(self):
        # Pass the path as argv (process.argv[1]) -- embedding a Windows path in
        # the -e source would mangle backslashes. Read + require from there.
        script = (
            "const p=process.argv[1];"
            "const e=require(p);"
            "process.stdout.write(JSON.stringify({"
            "keys:Object.keys(e),"
            "score:typeof e.score,"
            "bonus:typeof e.bonus"
            "}));"
        )
        out = subprocess.run([shutil.which("node"), "-e", script, MIRROR],
                             capture_output=True, text=True, cwd=ROOT, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        self.assertEqual(data["score"], "function")
        self.assertEqual(data["bonus"], "function")
        self.assertTrue(EXPECTED_EXPORTS.issubset(set(data["keys"])),
                        "missing exports: %s" % (EXPECTED_EXPORTS - set(data["keys"])))


if __name__ == "__main__":
    unittest.main(verbosity=2)
