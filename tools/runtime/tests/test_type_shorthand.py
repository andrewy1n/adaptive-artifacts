"""cmd_list's --type must resolve a short (unqualified) type name, or error --
never silently return an empty result set for a name that matches nothing."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
sys.path.insert(0, str(RUNTIME))

from support import (  # noqa: E402
    RESOLVED,
    load_json,
    make_git_repo,
    run_cli,
    sample_position_payload,
)


class TypeShorthandTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".type-shorthand-test"
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        r = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        r = run_cli(
            "create",
            "--type",
            "project:current-position",
            "--subject",
            "runtime",
            "--payload",
            sample_position_payload(),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.record = load_json(r.stdout)["record"]

    def test_short_type_name_resolves_to_qualified_type(self):
        r = run_cli("list", "--type", "current-position", store=self.store)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        body = load_json(r.stdout)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["records"][0]["id"], self.record["id"])

    def test_unknown_type_errors_instead_of_empty(self):
        r = run_cli("list", "--type", "no-such-type", store=self.store)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        body = load_json(r.stdout)
        self.assertEqual(body["error"], "unknown_type")

    def test_qualified_type_still_works(self):
        r = run_cli("list", "--type", "project:current-position", store=self.store)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        body = load_json(r.stdout)
        self.assertEqual(body["count"], 1)


if __name__ == "__main__":
    unittest.main()
