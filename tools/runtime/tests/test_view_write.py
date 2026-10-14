"""Tests for synchronizing all derived contract views to the store."""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
sys.path.insert(0, str(RUNTIME))

from support import RESOLVED, load_json, make_git_repo, run_cli  # noqa: E402


class ViewWriteTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".view-write-test"
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        result = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_view_write_writes_each_contract_view(self):
        result = run_cli("view", "--write", store=self.store)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        body = load_json(result.stdout)
        self.assertGreater(len(body["views"]), 0)
        for view_id in body["views"]:
            path = self.store / "views" / f"{view_id.split(':', 1)[-1]}.md"
            self.assertTrue(path.is_file(), path)
            self.assertIn("Derived view", path.read_text())


if __name__ == "__main__":
    unittest.main()
