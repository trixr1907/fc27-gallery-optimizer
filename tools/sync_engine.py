#!/usr/bin/env python3
"""Sync check: the engine block in index.html and engine/engine.js must be
byte-identical.

Direction (fixed, K1):  index.html  --(source of truth)-->  engine/engine.js (mirror)
The source is the block between the ENGINE START/END markers in index.html --
never the other way round. The compared block includes the guarded
module.exports line immediately after ENGINE END.

Usage:
    python3 tools/sync_engine.py          # write the mirror from index.html
    python3 tools/sync_engine.py --check  # verify byte equality, exit 1 on drift
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")
MIRROR = os.path.join(ROOT, "engine", "engine.js")
START = "// ===== ENGINE START ====="
END = "// ===== ENGINE END ====="


def extract_block(html_text):
    """Return the engine block from ENGINE START through the guarded exports line."""
    i = html_text.find(START)
    if i < 0:
        raise SystemExit("ERROR: ENGINE START marker not found in index.html")
    j = html_text.find(END, i)
    if j < 0:
        raise SystemExit("ERROR: ENGINE END marker not found in index.html")
    j += len(END)
    # include the following guarded module.exports line and its newline
    nl = html_text.find("\n", j)
    if nl < 0:
        raise SystemExit("ERROR: no line after ENGINE END marker")
    second = html_text.find("\n", nl + 1)
    line_end = second if second >= 0 else len(html_text)
    return html_text[i:line_end]


def main():
    with open(INDEX, "r", encoding="utf-8", newline="") as f:
        html = f.read()
    block = extract_block(html)

    if "--check" in sys.argv:
        with open(MIRROR, "r", encoding="utf-8", newline="") as f:
            mirror = f.read()
        if block == mirror:
            print("OK: engine.js is byte-identical to the index.html engine block")
            print("direction: index.html (source of truth) -> engine/engine.js (mirror)")
            print("block bytes: {}".format(len(block.encode("utf-8"))))
            print("exports line included in comparison: {}".format(
                "module.exports" in block))
            return 0
        print("FAIL: engine.js differs from the index.html engine block")
        print("direction: index.html (source of truth) -> engine/engine.js (mirror)")
        print("index block bytes:  {}".format(len(block.encode('utf-8'))))
        print("mirror bytes:       {}".format(len(mirror.encode('utf-8'))))
        # first divergence
        n = min(len(block), len(mirror))
        for k in range(n):
            if block[k] != mirror[k]:
                print("first divergence at char {}".format(k))
                print("  index : {!r}".format(block[max(0, k - 40):k + 40]))
                print("  mirror: {!r}".format(mirror[max(0, k - 40):k + 40]))
                break
        print("run: python3 tools/sync_engine.py   (to rewrite the mirror)")
        return 1

    with open(MIRROR, "w", encoding="utf-8", newline="") as f:
        f.write(block)
    print("wrote {} bytes to engine/engine.js".format(len(block.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
