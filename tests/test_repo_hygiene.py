#!/usr/bin/env python3
"""P4.5 -- repository hygiene, pinned so it cannot regress.

Two delivery-list items are reconciled here rather than left implicit:

  * `CHANGELOG.md` exists and records every delivered phase commit;
  * `LICENSE` is **deliberately absent** (the license is the owner's legal
    decision) and that reason is documented in BOTH `README.md` and
    `CHANGELOG.md`, so "no license" is a stated position, not an oversight.

Also checks the `.gitignore` covers the benchmark/probe scratch, so a local run
cannot accidentally commit a multi-hundred-KB JSON dump.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class TestChangelog(unittest.TestCase):
    def test_changelog_exists(self):
        self.assertTrue(os.path.exists(os.path.join(ROOT, "CHANGELOG.md")))

    def test_changelog_records_every_phase_commit(self):
        """Every SETTLED phase commit must be named, so the changelog is traceable
        back to the repository rather than being prose.

        The tip phase (P4) is deliberately excluded: the changelog is edited by
        the very commit that delivers it, so quoting that hash would invalidate
        itself on every amend.
        """
        text = read("CHANGELOG.md")
        for sha in ("a925878", "b5db154", "36fa5fb", "cfe0f6f", "cb8beef",
                    "1388934"):
            self.assertIn(sha, text, "CHANGELOG.md does not mention commit %s" % sha)
        # ... and the tip must explain why its own hash is absent.
        self.assertRegex(text, r"(?i)tip of the `master` history")

    def test_changelog_documents_the_dotfile_fix(self):
        text = read("CHANGELOG.md")
        self.assertIn("/.git/config", text)
        self.assertIn("404", text)


class TestLicenseIsDeliberatelyAbsent(unittest.TestCase):
    def test_no_license_file(self):
        entries = [n for n in os.listdir(ROOT) if n.lower().startswith("license")]
        self.assertEqual(entries, [],
                         "a LICENSE appeared; if that is intended, update the "
                         "documented reason and this test")

    def test_the_absence_is_documented_in_the_readme(self):
        readme = read("README.md")
        self.assertIn("No `LICENSE` file is included, deliberately", readme)
        self.assertIn("all rights reserved", readme.lower())

    def test_the_absence_is_documented_in_the_changelog(self):
        text = read("CHANGELOG.md")
        self.assertRegex(text, r"(?i)## License")
        self.assertIn("all rights reserved", text.lower())


class TestGitignoreCoversScratch(unittest.TestCase):
    def test_bench_and_probe_scratch_is_ignored(self):
        gi = read(".gitignore")
        for pat in ("_bench_*.json", "_tick*.js", "_gen*.js", "_ds.json"):
            self.assertIn(pat, gi, ".gitignore does not cover %s" % pat)

    def test_curated_evidence_is_not_ignored(self):
        """`docs/` holds the committed evidence and must not be excluded.

        Only PATTERN lines count -- the word "docs" may legitimately appear in a
        comment explaining where the curated evidence lives.
        """
        patterns = [ln.strip() for ln in read(".gitignore").splitlines()
                    if ln.strip() and not ln.lstrip().startswith("#")]
        self.assertFalse([p for p in patterns if p.startswith("docs")],
                         "docs/ must not be ignored: %s" % patterns)


if __name__ == "__main__":
    unittest.main()
