#!/usr/bin/env python3
"""P2.11 -- the remaining hardening items, each mapped to a test.

Covers what P2.6 did NOT: the ENV kill-switch for the importer, the per-client
rate limit, directory-listing containment, and `Cache-Control: no-store` on API
responses. No network is used.
"""
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server_harness import load_server  # noqa: E402

srv = load_server()


class TestImporterEnvSwitch(unittest.TestCase):
    def test_enabled_by_default(self):
        self.assertTrue(srv.importer_enabled({}))

    def test_disabled_values(self):
        for v in ("1", "true", "TRUE", "yes", "on", " On "):
            self.assertFalse(srv.importer_enabled({"FC27_NO_IMPORT": v}), v)

    def test_other_values_keep_it_enabled(self):
        for v in ("0", "false", "no", "", "off", "anything"):
            self.assertTrue(srv.importer_enabled({"FC27_NO_IMPORT": v}), v)


class TestRateLimiter(unittest.TestCase):
    def test_allows_up_to_max_then_blocks(self):
        now = [0.0]
        rl = srv.RateLimiter(3, 60.0, clock=lambda: now[0])
        self.assertTrue(rl.allow("a"))
        self.assertTrue(rl.allow("a"))
        self.assertTrue(rl.allow("a"))
        self.assertFalse(rl.allow("a"))      # 4th in the window
        now[0] = 61.0
        self.assertTrue(rl.allow("a"))       # window rolled over

    def test_keys_are_isolated(self):
        now = [0.0]
        rl = srv.RateLimiter(1, 60.0, clock=lambda: now[0])
        self.assertTrue(rl.allow("a"))
        self.assertFalse(rl.allow("a"))
        self.assertTrue(rl.allow("b"))       # a different client is unaffected

    def test_reset(self):
        now = [0.0]
        rl = srv.RateLimiter(1, 60.0, clock=lambda: now[0])
        rl.allow("a")
        rl.reset("a")
        self.assertTrue(rl.allow("a"))


class TestDirectoryContainment(unittest.TestCase):
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_directory_request_detected(self):
        self.assertTrue(srv.is_directory_request("/docs/"))
        self.assertTrue(srv.is_directory_request("/"))
        self.assertFalse(srv.is_directory_request("/index.html"))
        self.assertFalse(srv.is_directory_request("/docs/a.png"))

    def test_containment_accepts_inside(self):
        inside = os.path.join(self.BASE, "index.html")
        self.assertTrue(srv.is_within_base(self.BASE, inside))

    def test_containment_rejects_outside(self):
        outside = os.path.join(os.path.dirname(self.BASE), "elsewhere.txt")
        self.assertFalse(srv.is_within_base(self.BASE, outside))
        self.assertFalse(srv.is_within_base(self.BASE, None))


class TestHttpP211(unittest.TestCase):
    """Exercise Handler.do_GET against a fake socket (no real server)."""

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

    def test_api_response_is_no_store(self):
        h = self._handler("/api/health")
        h.do_GET()
        keys = {k.lower(): v for k, v in self.headers}
        self.assertEqual(keys.get("cache-control"), "no-store")

    def test_directory_listing_is_403(self):
        h = self._handler("/docs/")
        h.do_GET()
        self.assertEqual(self.status, 403)

    def test_rate_limit_returns_429(self):
        # Exhaust the limiter for the loopback client, then expect 429.
        srv.IMPORT_LIMITER.reset()
        for _ in range(srv.RATE_LIMIT_MAX):
            srv.IMPORT_LIMITER.allow("127.0.0.1")
        h = self._handler("/api/futgg?url=https://www.fut.gg/fut-gallery/x/")
        h.do_GET()
        self.assertEqual(self.status, 429)
        body = json.loads(h.wfile.getvalue().decode())
        self.assertEqual(body["error"], "rate_limited")
        srv.IMPORT_LIMITER.reset()

    def test_env_switch_disables_importer_503(self):
        os.environ["FC27_NO_IMPORT"] = "1"
        try:
            h = self._handler("/api/futgg?url=https://www.fut.gg/fut-gallery/x/")
            h.do_GET()
            self.assertEqual(self.status, 503)
            body = json.loads(h.wfile.getvalue().decode())
            self.assertEqual(body["error"], "importer_disabled")
        finally:
            os.environ.pop("FC27_NO_IMPORT", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
