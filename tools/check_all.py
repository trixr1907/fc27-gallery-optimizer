#!/usr/bin/env python3
"""One command that verifies the repository, locally and in CI.

Runs, in order:
  1. the engine mirror is byte-identical to the inline block in index.html;
  2. both copies of the engine parse (`node --check`);
  3. the full test suite (stdlib `unittest`), including the smoke tests.

Deliberately dependency-free: stdlib Python plus whatever `node` is on PATH.
If Node is missing, step 2 is SKIPPED (with a warning) rather than failed -- the
mirror check and the suite still run, and the suite itself skips the
Node-backed modules.

Exit code is 0 only if every executed step passed.
"""
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable or "python3"


def run(cmd, cwd=ROOT):
    t0 = time.perf_counter()
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (time.perf_counter() - t0) * 1000.0, p.stdout, p.stderr


def main():
    node = shutil.which("node")
    steps = [
        ("engine mirror byte-identical (index.html -> engine/engine.js)",
         [PY, "tools/sync_engine.py", "--check"], True),
        ("engine parses (node --check)",
         [node or "node", "--check", "engine/engine.js"], node is not None),
        ("test suite (unittest)",
         [PY, "-m", "unittest", "discover", "-s", "tests", "-q"], True),
    ]

    results, failed = [], False
    for name, cmd, enabled in steps:
        if not enabled:
            results.append((name, None, 0.0, "SKIPPED (node not on PATH)"))
            continue
        rc, ms, out, err = run(cmd)
        tail = (out or err or "").strip().splitlines()
        note = tail[-1] if tail else ""
        results.append((name, rc, ms, note))
        if rc != 0:
            failed = True
            print("\n---- %s FAILED ----" % name)
            print(out)
            print(err)

    width = max(len(r[0]) for r in results)
    print("\n=== fc27 verification ===")
    for name, rc, ms, note in results:
        status = "SKIP" if rc is None else ("PASS" if rc == 0 else "FAIL")
        print("  %-4s %-*s  %7.1f ms  %s" % (status, width, name, ms, note[:90]))
    print("=========================")
    print("RESULT:", "FAIL" if failed else "OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
