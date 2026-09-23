"""Ids are globally unique and opaque, so `get` should not require --type,
and a wrong --type must be distinguishable from a genuinely missing id."""

from __future__ import annotations

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


class GetWithoutTypeTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".get-without-type-test"
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

    def test_get_without_type_finds_the_record(self):
        r = run_cli("get", "--id", self.record["id"], store=self.store)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        body = load_json(r.stdout)
        self.assertEqual(body["id"], self.record["id"])

    def test_get_with_wrong_type_is_distinguishable_from_not_found(self):
        wrong = run_cli(
            "get",
            "--type",
            "project:active-goal",
            "--id",
            self.record["id"],
            store=self.store,
        )
        self.assertNotEqual(wrong.returncode, 0, wrong.stdout)
        wrong_body = load_json(wrong.stdout)
        self.assertEqual(wrong_body["error"], "wrong_type")

        missing = run_cli(
            "get",
            "--type",
            "project:current-position",
            "--id",
            "rec-00000000-0000-0000-0000-000000000000",
            store=self.store,
        )
        self.assertNotEqual(missing.returncode, 0, missing.stdout)
        missing_body = load_json(missing.stdout)
        self.assertEqual(missing_body["error"], "not_found")

    def test_get_without_type_and_missing_id_is_not_found(self):
        r = run_cli("get", "--id", "rec-00000000-0000-0000-0000-000000000000", store=self.store)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        body = load_json(r.stdout)
        self.assertEqual(body["error"], "not_found")


if __name__ == "__main__":
    unittest.main()
