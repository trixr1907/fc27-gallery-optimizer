#!/usr/bin/env python3
"""P2.2 -- Alias layer: canonicalise variant names/types consistently.

The server-side alias map must agree with the engine's JS `norm()` alias
handling, so imports, migration and eligibility all resolve the same concepts
the same way ("Team of the Week" == "TOTW"; "Heroes"/"Hero" == "heroic";
"Holographics" == "holographic"; club suffix/prefix noise dropped).

Pure functions, no network, no engine needed.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server_harness import load_server  # noqa: E402

srv = load_server()


class TestAliasCanonicalName(unittest.TestCase):
    def test_known_aliases_collapse(self):
        cases = {
            "Team of the Week": "totw",
            "team of the week": "totw",
            "TOTW": "totw",
            "Heroes": "heroic",
            "Hero": "heroic",
            "heroic": "heroic",
            "Holographics": "holographic",
            "Holographic": "holographic",
        }
        for raw, want in cases.items():
            self.assertEqual(srv.canonical_name(raw), want, raw)

    def test_accents_stripped(self):
        self.assertEqual(srv.canonical_name("Málaga"), "malaga")
        self.assertEqual(srv.canonical_name("Atlético"), "atletico")

    def test_club_noise_dropped(self):
        # "Málaga CF" must equal "Malaga" (suffix dropped, accents stripped).
        self.assertEqual(srv.canonical_name("Málaga CF"), "malaga")
        self.assertEqual(srv.canonical_name("Malaga"), "malaga")
        self.assertEqual(srv.canonical_name("AC Milan"), "milan")

    def test_none_and_empty_are_safe(self):
        self.assertEqual(srv.canonical_name(None), "")
        self.assertEqual(srv.canonical_name(""), "")
        self.assertEqual(srv.canonical_name("   "), "")

    def test_idempotent(self):
        for raw in ["Team of the Week", "Málaga CF", "Heroes", "Holographics"]:
            once = srv.canonical_name(raw)
            self.assertEqual(srv.canonical_name(once), once, raw)

    def test_type_alias_matches_name_alias(self):
        self.assertEqual(srv.canonical_type("Hero"), "heroic")
        self.assertEqual(srv.canonical_type("holographics"), "holographic")


class TestAliasParityWithEngine(unittest.TestCase):
    """The server alias table must match the engine's JS alias table exactly."""

    def _engine_alias_map(self):
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "index.html"), encoding="utf-8") as f:
            html = f.read()
        m = re.search(r"const alias = \{(.*?)\};", html, re.S)
        self.assertIsNotNone(m, "engine alias table not found")
        body = m.group(1)
        pairs = re.findall(r"'([^']+)'\s*:\s*'([^']+)'", body)
        return dict(pairs)

    def test_alias_tables_equal(self):
        engine = self._engine_alias_map()
        server = {k: v for k, v in srv.ALIASES.items()}
        self.assertEqual(server, engine,
                         "server ALIASES must equal the engine alias table")


if __name__ == "__main__":
    unittest.main(verbosity=2)
