#!/usr/bin/env python3
"""P2.1 -- Parser INTEGRATION (consume the P0 parser, do not rebuild it).

The endpoint `/api/futgg` must:
  * call the existing `parse_futgg` (the same code path the parser tests pin),
  * attach provenance to every successful import (sourceUrl, fetchedAt,
    schemaVersion, cached),
  * serve a second identical request from cache (cache hit, `cached: true`),
  * map non-set pages to 422 with the machine-readable reason unchanged.

The network is stubbed with the offline FUT.GG fixtures, so this runs in CI.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server_harness import load_server, fixture  # noqa: E402

srv = load_server()

MALAGA_URL = "https://www.fut.gg/fut-gallery/laliga/malaga-cf/"
INDEX_URL = "https://www.fut.gg/fut-gallery/rarities/"


class _FakeWfile(object):
    def __init__(self):
        self.buf = b""

    def write(self, b):
        self.buf += b


def make_handler(path):
    h = srv.Handler.__new__(srv.Handler)
    h.path = path
    h.wfile = _FakeWfile()
    h._captured = {"status": None, "headers": []}
    h.send_response = lambda code, *a, **k: h._captured.__setitem__("status", code)
    h.send_header = lambda k, v: h._captured["headers"].append((k, v))
    h.end_headers = lambda: None
    h.send_error = lambda code, msg=None, *a, **k: h._captured.__setitem__("status", code)
    h.log_message = h.log_error = h.log_request = lambda *a, **k: None
    h.request_version = "HTTP/1.1"
    return h


class TestParserIntegration(unittest.TestCase):
    def setUp(self):
        srv.PAGE_CACHE.clear()
        self._orig_urlopen = srv.urlopen
        # Stub the network: serve the matching offline fixture by URL.
        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else req
            if "malaga-cf" in url:
                raw = fixture("malaga_cf.html").encode("utf-8")
            elif "/rarities/" in url:
                raw = fixture("rarities_index.html").encode("utf-8")
            else:
                raw = fixture("malaga_cf.html").encode("utf-8")
            return _Resp(raw)
        srv.urlopen = fake_urlopen

    def tearDown(self):
        srv.urlopen = self._orig_urlopen
        srv.PAGE_CACHE.clear()

    def _get(self, url):
        from urllib.parse import quote
        h = make_handler("/api/futgg?url=" + quote(url, safe=""))
        h.do_GET()
        body = json.loads(h.wfile.buf.decode())
        return h._captured["status"], body

    def test_success_uses_parser_and_adds_provenance(self):
        status, body = self._get(MALAGA_URL)
        self.assertEqual(status, 200)
        # parser output (unchanged)
        self.assertEqual(body["id"], "malaga_cf")
        self.assertEqual(body["slots"], 15)
        self.assertEqual(sum(body["rewards"].values()), 28)
        # provenance / snapshot metadata
        self.assertEqual(body["sourceUrl"], MALAGA_URL)
        self.assertEqual(body["schemaVersion"], srv.SCHEMA_VERSION)
        self.assertTrue(body["fetchedAt"].endswith("Z"))
        self.assertFalse(body["cached"], "first request is a cache miss")

    def test_second_request_is_cache_hit(self):
        s1, b1 = self._get(MALAGA_URL)
        s2, b2 = self._get(MALAGA_URL)
        self.assertEqual((s1, s2), (200, 200))
        self.assertFalse(b1["cached"])
        self.assertTrue(b2["cached"], "second identical request must hit the cache")
        self.assertEqual(b1["id"], b2["id"])

    def test_parser_output_matches_direct_call(self):
        """The endpoint must return exactly what parse_futgg returns (+meta)."""
        raw = fixture("malaga_cf.html")
        direct = srv.parse_futgg(raw, MALAGA_URL)
        _, body = self._get(MALAGA_URL)
        for k, v in direct.items():
            self.assertEqual(body[k], v, k)

    def test_index_page_reason_preserved(self):
        status, body = self._get(INDEX_URL)
        self.assertEqual(status, 422)
        self.assertEqual(body["error"], "not_a_set_page")
        self.assertEqual(body["reason"], srv.R_INDEX_PAGE)

    def test_disallowed_url_never_fetches(self):
        called = {"n": 0}

        def boom(req, timeout=None):
            called["n"] += 1
            raise AssertionError("must not fetch a disallowed URL")

        srv.urlopen = boom
        status, body = self._get("https://evil.com/fut-gallery/x/")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "url_not_allowed")
        self.assertEqual(called["n"], 0)


class _Resp(object):
    def __init__(self, data):
        self._d = data

    def read(self, n=None):
        return self._d if n is None else self._d[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


if __name__ == "__main__":
    unittest.main(verbosity=2)
