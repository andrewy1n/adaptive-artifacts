"""Tests for capture bundle multiplicity and partial-write recovery."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
REPO_ROOT = RUNTIME.parent.parent
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(REPO_ROOT))

from support import (  # noqa: E402
    RESOLVED,
    load_json,
    make_git_repo,
    run_cli,
    sample_attempt_payload,
    sample_finding_payload,
    sample_investigation_question_payload,
    sample_observation_payload,
)
from store import Store  # noqa: E402


class CaptureMultiplicityTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".capture-test"
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        r = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def _capture(self, bundle: str, records: list[dict]):
        return run_cli(
            "capture",
            "--bundle",
            bundle,
            "--records",
            json.dumps(records),
            store=self.store,
        )

    def test_two_records_of_the_same_type_are_both_kept(self):
        r = self._capture(
            "project:concluded-investigation",
            [
                {
                    "type": "project:investigation-question",
                    "subject": "Are retries idempotent?",
                    "payload": sample_investigation_question_payload(),
                },
                {
                    "type": "project:investigation-observation",
                    "subject": "429 from vendor",
                    "payload": sample_observation_payload(),
                },
                {
                    "type": "project:investigation-observation",
                    "subject": "503 from vendor",
                    "payload": sample_observation_payload(what_was_observed="503 after retry"),
                },
                {
                    "type": "project:finding",
                    "subject": "retry semantics",
                    "payload": sample_finding_payload(),
                },
            ],
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        records = load_json(r.stdout)["records"]
        observations = records["project:investigation-observation"]
        self.assertIsInstance(observations, list)
        self.assertEqual(len(observations), 2)
        self.assertNotEqual(observations[0]["id"], observations[1]["id"])
        subjects = {o["subject"] for o in observations}
        self.assertEqual(subjects, {"429 from vendor", "503 from vendor"})
        # single-count types stay unwrapped, not single-item lists
        self.assertIsInstance(records["project:finding"], dict)

        stored = list(Store(self.store).iter_records("project:investigation-observation"))
        self.assertEqual(len(stored), 2)

    def test_missing_a_required_type_entirely_still_errors(self):
        r = self._capture(
            "project:concluded-investigation",
            [
                {
                    "type": "project:investigation-question",
                    "subject": "Are retries idempotent?",
                    "payload": sample_investigation_question_payload(),
                },
                {
                    "type": "project:finding",
                    "subject": "retry semantics",
                    "payload": sample_finding_payload(),
                },
            ],
        )
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["error"], "bundle_mismatch")


class CaptureRollbackTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".capture-rollback-test"
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        r = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def test_second_record_failing_leaves_no_partial_state(self):
        # project:abandoned-path creates project:investigation-observation first
        # (failed-attempt links to it), so the observation is written, then the
        # failed-attempt fails validation (missing required "retry_when").
        invalid_attempt_payload = sample_attempt_payload()
        del invalid_attempt_payload["retry_when"]
        r = run_cli(
            "capture",
            "--bundle",
            "project:abandoned-path",
            "--records",
            json.dumps(
                [
                    {
                        "type": "project:investigation-observation",
                        "subject": "429 from vendor",
                        "payload": sample_observation_payload(),
                    },
                    {
                        "type": "project:failed-attempt",
                        "subject": "naive retry loop",
                        "payload": invalid_attempt_payload,
                    },
                ]
            ),
            store=self.store,
        )
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["error"], "validation")

        store = Store(self.store)
        self.assertEqual(list(store.iter_records("project:investigation-observation")), [])
        self.assertEqual(list(store.iter_records("project:failed-attempt")), [])
        # the append-only observation's history snapshot must be rolled back too
        history_dir = self.store / "history" / "project__investigation-observation"
        self.assertFalse(history_dir.is_dir() and any(history_dir.rglob("*.md")))

        r = run_cli("validate", store=self.store)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_successful_bundle_still_links_relationship(self):
        r = run_cli(
            "capture",
            "--bundle",
            "project:abandoned-path",
            "--records",
            json.dumps(
                [
                    {
                        "type": "project:failed-attempt",
                        "subject": "naive retry loop",
                        "payload": sample_attempt_payload(),
                    },
                    {
                        "type": "project:investigation-observation",
                        "subject": "429 from vendor",
                        "payload": sample_observation_payload(),
                    },
                ]
            ),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        records = load_json(r.stdout)["records"]
        attempt = records["project:failed-attempt"]
        observation = records["project:investigation-observation"]
        self.assertEqual(attempt["relationships"]["informed_by"], [observation["id"]])


if __name__ == "__main__":
    unittest.main()
