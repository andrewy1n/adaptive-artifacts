"""--expected-revision @current means "re-read and use whatever is current",
letting a caller mutate a record it just created/read without a separate
`get` round trip first. The strict form (an exact revision string) must keep
working unchanged -- that's the real optimistic-concurrency guard."""

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
    sample_finding_payload,
    sample_position_payload,
)


class ExpectedRevisionCurrentTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".expected-revision-current-test"
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        r = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def _create(self, record_type: str, subject: str, payload: dict) -> dict:
        r = run_cli(
            "create",
            "--type",
            record_type,
            "--subject",
            subject,
            "--payload",
            json.dumps(payload),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return load_json(r.stdout)["record"]

    def test_update_with_at_current_skips_the_read(self):
        finding = self._create("project:finding", "retry semantics", sample_finding_payload())
        r = run_cli(
            "update",
            "--type",
            finding["record_type"],
            "--id",
            finding["id"],
            "--transition",
            "supported",
            "--expected-revision",
            "@current",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = load_json(r.stdout)
        self.assertEqual(body["record"]["lifecycle_state"], "supported")

    def test_update_with_exact_stale_revision_still_rejected(self):
        finding = self._create("project:finding", "retry semantics", sample_finding_payload())
        r = run_cli(
            "update",
            "--type",
            finding["record_type"],
            "--id",
            finding["id"],
            "--transition",
            "supported",
            "--expected-revision",
            "sha256:not-the-real-revision",
            store=self.store,
        )
        self.assertEqual(r.returncode, 2)
        self.assertEqual(load_json(r.stdout)["error"], "stale_write")

    def test_supersede_with_at_current(self):
        record = self._create(
            "project:current-position", "runtime", json.loads(sample_position_payload())
        )
        r = run_cli(
            "supersede",
            "--type",
            record["record_type"],
            "--id",
            record["id"],
            "--expected-revision",
            "@current",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = load_json(r.stdout)
        self.assertNotEqual(body["record"]["id"], record["id"])

    def test_contradict_with_at_current(self):
        finding = self._create("project:finding", "retry semantics", sample_finding_payload())
        r = run_cli(
            "contradict",
            "--type",
            finding["record_type"],
            "--id",
            finding["id"],
            "--expected-revision",
            "@current",
            "--subject",
            "retries are idempotent after all",
            "--payload",
            json.dumps(sample_finding_payload(claim="vendor retries are idempotent")),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
