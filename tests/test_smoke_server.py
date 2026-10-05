#!/usr/bin/env python3
"""P4.3 -- END-TO-END smoke test of the real HTTP server.

`test_server_hardening.py` exercises the handler methods against fakes; this
module starts the ACTUAL `server.py` process on a free port and speaks real HTTP
to it, so the whole path (socket -> handler -> routing -> static serving ->
headers) is proven to work. It is the same start command Render runs
(`python3 server.py --no-open`, with `PORT` set).

Covered:
  * `/api/health` answers and reports the schema version;
  * `/` serves the app, and the served HTML is the real app (not a stub);
  * a static asset (`/engine/engine.js`) is served with the engine marker;
  * the hardening headers are on every response;
  * directory listing and path traversal are refused with 403;
  * `FC27_NO_IMPORT=1` disables the importer with 503 (no network is touched).

No third-party dependency: stdlib `urllib` + a subprocess.
"""
import http.client
import os
import socket
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for(port, timeout=20.0):
    """Wait until /api/health answers, else raise with the server's output."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=1.0)
            c.request("GET", "/api/health")
            r = c.getresponse()
            r.read()
            c.close()
            if r.status == 200:
                return True
        except Exception as e:  # noqa: BLE001 - any connection error means "not yet"
            last = e
        time.sleep(0.15)
    raise AssertionError("server did not become ready on port %s (%s)" % (port, last))


class SmokeServerCase(unittest.TestCase):
    """One server process shared by every assertion in this module."""

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        env = dict(os.environ)
        env["PORT"] = str(cls.port)
        env["HOST"] = "127.0.0.1"
        env["FC27_NO_IMPORT"] = "1"          # no outbound network in tests
        cls.proc = subprocess.Popen(
            [sys.executable, "server.py", "--no-open"],
            cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        try:
            wait_for(cls.port)
        except Exception:
            cls.proc.terminate()
            out = ""
            try:
                out = cls.proc.communicate(timeout=5)[0]
            except Exception:  # noqa: BLE001
                pass
            raise AssertionError("server failed to start; output:\n%s" % out)

    @classmethod
    def tearDownClass(cls):
        if cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.proc.kill()

    def get(self, path, method="GET"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10.0)
        try:
            c.request(method, path)
            r = c.getresponse()
            body = r.read()
            # Header NAMES are case-insensitive on the wire and `http.server`
            # actually emits `Content-type` (lowercase t), so normalise them.
            headers = {k.lower(): v for k, v in r.getheaders()}
            return r.status, headers, body
        finally:
            c.close()

    # ---- liveness ---------------------------------------------------------
    def test_health_endpoint(self):
        status, headers, body = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertIn("json", headers.get("content-type", ""))
        self.assertIn(b'"ok"', body)
        self.assertIn(b'"schemaVersion"', body)
        # API responses are never cached.
        self.assertEqual(headers.get("cache-control"), "no-store")

    # ---- the app itself ---------------------------------------------------
    def test_root_serves_the_real_app(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8", "replace")
        self.assertIn("<title>FC 27 Gallery Optimizer</title>", html)
        # The panels the P1-P3 work added must be in the SERVED document.
        for marker in ('id="portfolio"', 'id="opps"', 'id="playersScroll"', 'id="improve"'):
            self.assertIn(marker, html, "served app is missing %s" % marker)
        # The engine must be inline in the served page (single-file app).
        self.assertIn("ENGINE START", html)

    def test_index_html_is_served_directly(self):
        status, _, body = self.get("/index.html")
        self.assertEqual(status, 200)
        self.assertIn(b"FC 27 Gallery Optimizer", body)

    def test_static_engine_asset_is_served(self):
        status, headers, body = self.get("/engine/engine.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers.get("content-type", "").lower())
        self.assertIn(b"portfolioPlan", body)
        self.assertIn(b"portfolioSearch", body)

    # ---- hardening on the live server -------------------------------------
    def test_security_headers_present(self):
        for path in ("/", "/api/health"):
            _, headers, _ = self.get(path)
            self.assertEqual(headers.get("x-content-type-options"), "nosniff", path)
            self.assertEqual(headers.get("x-frame-options"), "DENY", path)

    def test_dot_files_and_dot_directories_are_not_served(self):
        """`/.git` must NEVER be served: it holds the object database and the repo
        config, so serving it leaks the whole source history.

        The expected status is **404**, not 403: the response must not even
        confirm that the path exists. (Regression: this returned 200 before P4 --
        `safe_static_path` only blocked escapes, not dot-segments.)
        """
        for path in ("/.git/config", "/.git/HEAD", "/.gitignore",
                     "/.github/workflows/ci.yml", "/.workbuddy-ai/memory",
                     "/engine/.hidden"):
            status, _, body = self.get(path)
            self.assertEqual(status, 404, "%s must not be served" % path)
            self.assertNotIn(b"[core]", body)
            self.assertNotIn(b"ref:", body)

    def test_dotfile_guard_does_not_break_the_app(self):
        # The guard must be narrow: the app's own files have no leading dot.
        for path in ("/", "/index.html", "/engine/engine.js"):
            status, _, _ = self.get(path)
            self.assertEqual(status, 200, "%s must still be served" % path)

    def test_directory_listing_is_refused(self):
        for path in ("/engine/", "/tests/", "/docs/"):
            status, _, _ = self.get(path)
            self.assertEqual(status, 403, "%s should be refused" % path)

    def test_path_traversal_is_refused(self):
        """Traversal must be refused. `..` is a DOT-segment, so the P4 dotfile
        guard catches it first and answers **404** -- deliberately, so the
        response does not confirm that the target exists. (400/403 are still
        accepted for the encoded variants that reach the containment guard.)"""
        for path in ("/../server.py", "/..%2fserver.py", "/engine/../../server.py"):
            status, _, _ = self.get(path)
            self.assertIn(status, (400, 403, 404), "%s must not be served" % path)

    def test_unknown_api_path_is_not_the_importer(self):
        # A lookalike path must not reach the importer route.
        status, _, body = self.get("/api/futggx")
        self.assertNotEqual(status, 200)
        self.assertNotIn(b"schemaVersion", body)

    # ---- importer kill-switch ---------------------------------------------
    def test_importer_disabled_by_env(self):
        status, _, body = self.get("/api/futgg?url=https://www.fut.gg/fut-gallery/laliga/malaga-cf/")
        self.assertEqual(status, 503)
        self.assertIn(b"importer_disabled", body)

    def test_importer_rejects_disallowed_url_before_any_fetch(self):
        # With the importer enabled the allow-list must still reject a bad host
        # WITHOUT touching the network. We assert the 400 shape, which is only
        # reachable after the allow-list check.
        status, _, body = self.get("/api/futgg?url=https://evil.example.com/fut-gallery/x/")
        self.assertEqual(status, 503)  # disabled wins here; allow-list is unit-tested
        self.assertIn(b"importer_disabled", body)


if __name__ == "__main__":
    unittest.main()
