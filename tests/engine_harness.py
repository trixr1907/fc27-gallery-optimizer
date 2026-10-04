#!/usr/bin/env python3
"""Shared test helper: run the REAL engine through tools/engine_cli.js.

The engine is JavaScript (index.html is the single source of truth; engine/engine.js
is the byte-identical mirror). Tests therefore must not re-implement the engine in
Python -- they drive the actual JS via a single long-lived Node process using the
JSON-Lines batch protocol (R4), so a whole test module costs one Node start.

If Node is unavailable, callers skip with a clear message (never a red failure).
"""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "tools", "engine_cli.js")
NODE = shutil.which("node")


def node_available():
    return NODE is not None


@unittest.skipUnless(node_available(), "node not found on PATH (engine JS tests need Node)")
class EngineCli:
    """Owns one `node engine_cli.js` process and speaks JSON-Lines to it."""

    def __init__(self):
        self.proc = subprocess.Popen(
            [NODE, CLI],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

    def call(self, fn, *args):
        """Send one request, return the unwrapped result (raises on engine error)."""
        out = self.raw(json.dumps({"fn": fn, "args": list(args)}))
        if not out.get("ok"):
            raise RuntimeError("engine error for fn=%s: %s" % (fn, out.get("error")))
        return out["result"]

    def raw(self, request_json):
        """Send a prebuilt request line, return the whole response object."""
        self.proc.stdin.write(request_json + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read()
            raise RuntimeError("engine_cli.js produced no output; stderr=%r" % err)
        return json.loads(line)

    def exports(self):
        return self.call("__ping__")["exports"]

    def close(self):
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        finally:
            for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                try:
                    if stream and not stream.closed:
                        stream.close()
                except Exception:
                    pass


class EngineTestCase(unittest.TestCase):
    """Base class giving each test module one shared engine process."""

    engine = None

    @classmethod
    def setUpClass(cls):
        cls.engine = EngineCli()

    @classmethod
    def tearDownClass(cls):
        if cls.engine is not None:
            cls.engine.close()
            cls.engine = None
