#!/usr/bin/env python3
"""P2.6 -- Server hardening, tested guard by guard.

Covers: the FUT.GG SSRF allow-list (exact host + path prefix + scheme, no
userinfo/port/fragment), the static path-traversal guard, the HTTP method
allow-list, the response size cap, and the security headers / safe error bodies.
No network is used: the handler methods are exercised against fakes.
"""
import importlib.util
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server_harness import load_server  # noqa: E402

srv = load_server()


class TestSsrfAllowList(unittest.TestCase):
    def test_valid_gallery_urls_allowed(self):
        for u in [
            "https://www.fut.gg/fut-gallery/laliga/malaga-cf/",
            "https://www.fut.gg/fut-gallery/leagues/premier-league/",
            "https://www.fut.gg/fut-gallery/rarities/totw/",
            "https://www.fut.gg/fut-gallery/",
        ]:
            self.assertTrue(srv.is_allowed_futgg_url(u), u)

    def test_host_lookalikes_rejected(self):
        for u in [
            "https://fut.gg/fut-gallery/x/",                       # nested host
            "https://www.fut.gg.evil.com/fut-gallery/x/",          # suffix attack
            "https://evil.com/www.fut.gg/fut-gallery/x/",          # prefix in path
            "https://www.fut.gg@evil.com/fut-gallery/x/",          # userinfo
            "http://www.fut.gg/fut-gallery/x/",                    # not https
            "https://www.fut.gg:8443/fut-gallery/x/",              # non-default port
        ]:
            self.assertFalse(srv.is_allowed_futgg_url(u), u)

    def test_path_prefix_enforced(self):
        for u in [
            "https://www.fut.gg/leagues/premier-league/",   # not under /fut-gallery/
            "https://www.fut.gg/",                          # root
            "https://www.fut.gg/fut-galleryX/x/",           # prefix confusion
        ]:
            self.assertFalse(srv.is_allowed_futgg_url(u), u)

    def test_fragment_rejected(self):
        self.assertFalse(
            srv.is_allowed_futgg_url("https://www.fut.gg/fut-gallery/x/#frag"))

    def test_non_string_safe(self):
        self.assertFalse(srv.is_allowed_futgg_url(None))
        self.assertFalse(srv.is_allowed_futgg_url(""))
        self.assertFalse(srv.is_allowed_futgg_url(123))


class TestStaticPathGuard(unittest.TestCase):
    BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def test_root_and_index_allowed(self):
        self.assertIsNotNone(srv.safe_static_path(self.BASE, "/"))
        self.assertIsNotNone(srv.safe_static_path(self.BASE, "/index.html"))

    def test_traversal_rejected(self):
        for p in ["/../server.py", "/..%2f..%2fetc%2fpasswd",
                  "/../../../../etc/passwd", "/a/../../b"]:
            self.assertIsNone(srv.safe_static_path(self.BASE, p), p)

    def test_absolute_and_nul_rejected(self):
        self.assertIsNone(srv.safe_static_path(self.BASE, "/C:/Windows/system32"))
        self.assertIsNone(srv.safe_static_path(self.BASE, "/a\x00b"))

    def test_nested_file_allowed(self):
        got = srv.safe_static_path(self.BASE, "/docs/../index.html")
        self.assertIsNotNone(got)
        self.assertTrue(got.endswith("index.html"))


class TestHttpHardening(unittest.TestCase):
    """Exercise the Handler against a fake socket (no real server)."""

    class _FakeWfile(io.BytesIO):
        pass

    def _handler(self, path="/api/futgg?url="):
        h = srv.Handler.__new__(srv.Handler)
        h.path = path
        h.wfile = self._FakeWfile()
        h.client_address = ("127.0.0.1", 12345)
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        self.status = None
        self.headers = []
        h.send_response = lambda code, *a, **k: setattr(self, "status", code)
        h.send_header = lambda k, v: self.headers.append((k, v))
        h.end_headers = lambda: None
        h.log_message = lambda *a, **k: None
        h.log_error = lambda *a, **k: None
        h.log_request = lambda *a, **k: None
        h.send_error = lambda code, msg=None, *a, **k: setattr(self, "status", code)
        return h

    def test_post_is_405(self):
        h = self._handler()
        h.do_POST()
        self.assertEqual(self.status, 405)

    def test_head_is_405(self):
        h = self._handler()
        h.do_HEAD()
        self.assertEqual(self.status, 405)

    def test_disallowed_url_is_400(self):
        h = self._handler("/api/futgg?url=https://evil.com/x")
        h.do_GET()
        self.assertEqual(self.status, 400)
        body = json.loads(h.wfile.getvalue().decode())
        self.assertEqual(body["error"], "url_not_allowed")

    def test_traversal_static_is_refused(self):
        """Traversal must never be served.

        P4 tightened this: `..` is a DOT-segment, so the new dot-segment guard
        answers **404** (deliberately -- the response must not confirm that the
        target exists). The containment guard's 403 remains reachable for the
        encoded variants, so both codes are accepted here.
        """
        for path in ("/../../etc/passwd", "/..%2fetc/passwd"):
            self.setUp()
            h = self._handler(path)
            h.do_GET()
            self.assertIn(self.status, (400, 403, 404),
                          "%s must not be served" % path)

    def test_dotfile_static_is_404(self):
        """`/.git/config` must be 404 -- it exposes the repository config and,
        with `/.git/`, the whole object database (regression: was 200)."""
        for path in ("/.git/config", "/.git/HEAD", "/.gitignore"):
            self.setUp()
            h = self._handler(path)
            h.do_GET()
            self.assertEqual(self.status, 404, "%s must not be served" % path)

    def test_health_ok(self):
        h = self._handler("/api/health")
        h.do_GET()
        self.assertEqual(self.status, 200)
        body = json.loads(h.wfile.getvalue().decode())
        self.assertTrue(body["ok"])
        self.assertEqual(body["schemaVersion"], srv.SCHEMA_VERSION)

    def test_security_headers_present(self):
        """Handler.end_headers() (real method) must emit the security headers."""
        h = srv.Handler.__new__(srv.Handler)
        sent = []
        h.send_header = lambda k, v: sent.append((k, v))
        h._headers_buffer = []
        h.wfile = self._FakeWfile()
        h.request_version = "HTTP/1.1"
        h.end_headers()
        keys = {k.lower() for k, _ in sent}
        self.assertIn("x-content-type-options", keys)
        self.assertIn("x-frame-options", keys)
        self.assertIn("referrer-policy", keys)


class TestSizeCap(unittest.TestCase):
    def test_cap_constant_is_sane(self):
        self.assertGreaterEqual(srv.MAX_FETCH_BYTES, 1024 * 1024)
        self.assertLessEqual(srv.MAX_FETCH_BYTES, 64 * 1024 * 1024)

    def test_oversize_fetch_raises_response_too_large(self):
        """_fetch must raise ValueError('response_too_large') past the cap."""
        class FakeResp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        big = b"x" * (srv.MAX_FETCH_BYTES + 10)
        h = srv.Handler.__new__(srv.Handler)

        orig = srv.urlopen
        srv.urlopen = lambda req, timeout=None: FakeResp(big)
        try:
            with self.assertRaises(ValueError) as cm:
                h._fetch("https://www.fut.gg/fut-gallery/x/")
            self.assertEqual(str(cm.exception), "response_too_large")
        finally:
            srv.urlopen = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
