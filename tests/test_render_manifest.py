#!/usr/bin/env python3
"""P4.4 -- Render deploy: verify what can be verified locally, state the rest.

An actual Render deploy was NOT performed (no Render account/CLI in this
environment), so this module does two honest things:

  1. It validates the Blueprint (`render.yaml`) STRUCTURALLY -- without PyYAML,
     because adding a dependency just for a test would violate the "no new
     runtime dependencies" rule. It checks the service type, runtime, the build
     command and the start command.
  2. It RUNS the exact start command the Blueprint declares, locally, with `PORT`
     set and `HOST` unset -- the same environment Render provides -- and asserts
     the server actually binds and serves the app.

What this proves: the manifest is well-formed and its start command works under
Render's environment contract. What it does NOT prove: that render.com builds and
routes it. That limitation is stated in VERIFICATION.md and the README, and this
module asserts the disclaimer is present so it cannot be quietly dropped.
"""
import http.client
import os
import re
import socket
import subprocess
import sys
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
MANIFEST = os.path.join(_ROOT, "render.yaml")
EXPECTED_START = "python3 server.py --no-open"


def read_manifest():
    with open(MANIFEST, encoding="utf-8") as f:
        return f.read()


class TestRenderBlueprint(unittest.TestCase):
    def test_manifest_exists_and_is_a_web_service(self):
        text = read_manifest()
        # Minimal structural parse (no PyYAML): the fields we depend on must be
        # present with the right shape.
        self.assertRegex(text, r"(?m)^services:\s*$")
        self.assertRegex(text, r"(?m)^\s*-\s*type:\s*web\s*$")
        self.assertRegex(text, r"(?m)^\s*runtime:\s*python\s*$")

    def test_start_command_is_the_supported_one(self):
        text = read_manifest()
        m = re.search(r'(?m)^\s*startCommand:\s*"([^"]+)"\s*$', text)
        self.assertIsNotNone(m, "render.yaml has no startCommand")
        self.assertEqual(m.group(1), EXPECTED_START)
        # The flag the start command relies on must exist in server.py.
        with open(os.path.join(_ROOT, "server.py"), encoding="utf-8") as f:
            server = f.read()
        self.assertIn("--no-open", server)
        self.assertIn("os.environ.get('PORT'", server)
        # Render supplies PORT; the server must bind 0.0.0.0 in that case.
        self.assertIn("'0.0.0.0' if os.environ.get('PORT') else '127.0.0.1'", server)

    def test_build_command_is_a_no_op(self):
        text = read_manifest()
        m = re.search(r'(?m)^\s*buildCommand:\s*"([^"]*)"\s*$', text)
        self.assertIsNotNone(m, "render.yaml has no buildCommand")
        self.assertIn("echo", m.group(1), "the build step must be an explicit no-op")


class TestRenderStartCommandLocally(unittest.TestCase):
    """Run Render's start command locally under Render's environment contract."""

    @classmethod
    def setUpClass(cls):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        cls.port = s.getsockname()[1]
        s.close()
        env = dict(os.environ)
        env["PORT"] = str(cls.port)          # Render sets PORT
        env.pop("HOST", None)                # ... and does NOT set HOST
        env["FC27_NO_IMPORT"] = "1"          # no outbound network during tests
        cls.proc = subprocess.Popen(
            [sys.executable, "server.py", "--no-open"],   # same args as the manifest
            cwd=_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                c = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=1)
                c.request("GET", "/api/health")
                r = c.getresponse()
                r.read()
                c.close()
                if r.status == 200:
                    return
            except Exception:  # noqa: BLE001
                time.sleep(0.15)
        cls.proc.terminate()
        raise AssertionError("the Render start command did not serve within 20 s")

    @classmethod
    def tearDownClass(cls):
        if cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.proc.kill()

    def test_binds_and_serves_with_only_port_set(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            c.request("GET", "/")
            r = c.getresponse()
            body = r.read()
        finally:
            c.close()
        self.assertEqual(r.status, 200)
        self.assertIn(b"FC 27 Gallery Optimizer", body)


class TestDeployLimitationIsDocumented(unittest.TestCase):
    """The agreed wording: no Render deploy is claimed unless it was tested."""

    def test_readme_states_the_deploy_was_not_verified(self):
        with open(os.path.join(_ROOT, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        self.assertIn("render.yaml", readme)
        self.assertRegex(
            readme,
            r"(?i)(not verified|not been verified|no deploy|unverified)")

    def test_verification_md_states_the_deploy_was_not_verified(self):
        with open(os.path.join(_ROOT, "VERIFICATION.md"), encoding="utf-8") as f:
            ver = f.read()
        self.assertRegex(ver, r"(?i)Render")
        self.assertRegex(
            ver,
            r"(?i)(not verified|not been verified|no deploy|unverified)")


if __name__ == "__main__":
    unittest.main()
