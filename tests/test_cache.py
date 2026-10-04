#!/usr/bin/env python3
"""P2.3 -- TTL fetch cache: bounded, expiring, deterministic (injected clock).

The cache must serve repeated FUT.GG imports without re-fetching, expire entries
after its TTL, and never grow past its bound. The clock is injected so the tests
never sleep.
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server_harness import load_server  # noqa: E402

srv = load_server()


class FakeClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class TestTTLCache(unittest.TestCase):
    def make(self, ttl=300, cap=32):
        self.clock = FakeClock()
        return srv.TTLCache(ttl_seconds=ttl, max_items=cap, clock=self.clock)

    def test_miss_then_hit(self):
        c = self.make()
        self.assertIsNone(c.get("a"))
        c.put("a", "page-a")
        self.assertEqual(c.get("a"), "page-a")

    def test_expiry_after_ttl(self):
        c = self.make(ttl=100)
        c.put("a", "page-a")
        self.clock.advance(99)
        self.assertEqual(c.get("a"), "page-a", "still inside TTL")
        self.clock.advance(1)  # now exactly at TTL -> expired
        self.assertIsNone(c.get("a"))

    def test_expired_entry_is_removed(self):
        c = self.make(ttl=10)
        c.put("a", 1)
        self.clock.advance(10)
        c.get("a")
        self.assertEqual(len(c), 0, "an expired lookup must evict the entry")

    def test_bound_evicts_oldest(self):
        c = self.make(ttl=1000, cap=2)
        c.put("a", 1)
        self.clock.advance(1)
        c.put("b", 2)
        self.clock.advance(1)
        c.put("c", 3)                      # cap reached -> oldest ("a") evicted
        self.assertIsNone(c.get("a"))
        self.assertEqual(c.get("b"), 2)
        self.assertEqual(c.get("c"), 3)
        self.assertEqual(len(c), 2)

    def test_update_existing_does_not_evict(self):
        c = self.make(ttl=1000, cap=1)
        c.put("a", 1)
        c.put("a", 2)                      # same key, still one entry
        self.assertEqual(len(c), 1)
        self.assertEqual(c.get("a"), 2)

    def test_clear(self):
        c = self.make()
        c.put("a", 1)
        c.put("b", 2)
        c.clear()
        self.assertEqual(len(c), 0)

    def test_thread_safety_smoke(self):
        """Concurrent puts/gets must not raise or corrupt the bound."""
        c = self.make(ttl=1000, cap=50)

        def worker(n):
            for i in range(200):
                c.put("k%d" % ((n + i) % 80), i)
                c.get("k%d" % (i % 80))

        ts = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertLessEqual(len(c), 50)


class TestPageCacheDefaults(unittest.TestCase):
    def test_module_level_cache_is_bounded_and_ttl(self):
        self.assertIsInstance(srv.PAGE_CACHE, srv.TTLCache)
        self.assertEqual(srv.PAGE_CACHE.max, 32)
        self.assertEqual(srv.PAGE_CACHE.ttl, 300)


if __name__ == "__main__":
    unittest.main(verbosity=2)
