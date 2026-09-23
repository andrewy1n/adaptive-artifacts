"""`update` should allow a same-state payload/body edit without --transition.
Previously --transition was required, so `in_progress -> in_progress`-style
edits were rejected as invalid_transition; `supersede` isn't a general
workaround since not every type declares a supersedes relationship. Append-
only records must still reject any mutation, transition or not."""

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
    sample_observation_payload,
    sample_question_payload,
)


class UpdateWithoutTransitionTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".update-without-transition-test"
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        r = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def _create(self, record_type: str, subject: str, payload) -> dict:
        r = run_cli(
            "create",
            "--type",
            record_type,
            "--subject",
            subject,
            "--payload",
            json.dumps(payload) if isinstance(payload, dict) else payload,
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return load_json(r.stdout)["record"]

    def test_update_without_transition_patches_payload_in_place(self):
        record = self._create(
            "project:continuity-question",
            "who owns the retry policy",
            sample_question_payload(),
        )
        self.assertEqual(record["lifecycle_state"], "open")
        r = run_cli(
            "update",
            "--type",
            record["record_type"],
            "--id",
            record["id"],
            "--expected-revision",
            record["revision"],
            "--payload",
            json.dumps({"owner": "someone-else"}),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        updated = load_json(r.stdout)["record"]
        self.assertEqual(updated["lifecycle_state"], "open")
        self.assertEqual(updated["payload"]["owner"], "someone-else")

    def test_append_only_record_still_rejects_update_without_transition(self):
        record = self._create(
            "project:investigation-observation",
            "429 from vendor",
            sample_observation_payload(),
        )
        r = run_cli(
            "update",
            "--type",
            record["record_type"],
            "--id",
            record["id"],
            "--expected-revision",
            record["revision"],
            "--payload",
            json.dumps({"what_was_observed": "quietly rewritten"}),
            store=self.store,
        )
        self.assertEqual(r.returncode, 3)
        self.assertEqual(load_json(r.stdout)["error"], "append_only")


if __name__ == "__main__":
    unittest.main()
