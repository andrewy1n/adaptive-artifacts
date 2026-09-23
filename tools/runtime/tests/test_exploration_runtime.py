"""Tests for exploration records on the generic contract runtime."""

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
from contract import load_contract  # noqa: E402
from handoff import generate_view  # noqa: E402
from store import Store  # noqa: E402


class ExplorationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".continuity-test"
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))

    def _init(self):
        r = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def _create(self, record_type: str, subject: str, payload: dict, *extra: str):
        r = run_cli(
            "create",
            "--type",
            record_type,
            "--subject",
            subject,
            "--payload",
            json.dumps(payload),
            *extra,
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return load_json(r.stdout)["record"]

    def test_observation_create_is_append_only(self):
        self._init()
        rec = self._create(
            "project:investigation-observation",
            "429 from vendor",
            sample_observation_payload(),
        )
        self.assertEqual(rec["lifecycle_state"], "recorded")
        self.assertNotIn("stewardship", rec)
        self.assertEqual(rec["provenance"]["sources"], ["vendor-docs"])
        history = Store(self.store).history_snapshot_path(
            rec["record_type"], rec["id"], rec["revision"]
        )
        self.assertTrue(history.is_file())
        r = run_cli(
            "update",
            "--type",
            rec["record_type"],
            "--id",
            rec["id"],
            "--transition",
            "recorded",
            "--expected-revision",
            rec["revision"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 3)
        self.assertIn("append_only", r.stdout)

    def test_occurrence_correction_keeps_original_recorded(self):
        self._init()
        original = self._create(
            "project:investigation-observation",
            "429 from vendor",
            sample_observation_payload(),
        )
        r = run_cli(
            "correct",
            "--type",
            original["record_type"],
            "--id",
            original["id"],
            "--payload",
            json.dumps(sample_observation_payload(what_was_observed="429 then 503")),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = load_json(r.stdout)
        successor = body["record"]
        self.assertNotEqual(successor["id"], original["id"])
        self.assertEqual(successor["relationships"]["corrects"], [original["id"]])
        live_original = load_json(
            run_cli(
                "get",
                "--type",
                original["record_type"],
                "--id",
                original["id"],
                store=self.store,
            ).stdout
        )
        self.assertEqual(live_original["lifecycle_state"], "recorded")
        self.assertEqual(live_original["revision"], original["revision"])
        r = run_cli("validate", store=self.store)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_second_corrector_of_same_original_fails_validation(self):
        self._init()
        original = self._create(
            "project:investigation-observation",
            "429 from vendor",
            sample_observation_payload(),
        )
        run_cli(
            "correct",
            "--type",
            original["record_type"],
            "--id",
            original["id"],
            "--payload",
            json.dumps(sample_observation_payload(what_was_observed="first correction")),
            store=self.store,
        )
        r = run_cli(
            "correct",
            "--type",
            original["record_type"],
            "--id",
            original["id"],
            "--payload",
            json.dumps(sample_observation_payload(what_was_observed="second correction")),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        r = run_cli("validate", store=self.store)
        self.assertEqual(r.returncode, 4)
        self.assertTrue(
            any("exactly one correcting successor" in e for e in load_json(r.stdout)["errors"])
        )

    def test_abandoned_path_bundle_writes_informed_by(self):
        self._init()
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
        body = load_json(r.stdout)
        attempt = body["records"]["project:failed-attempt"]
        observation = body["records"]["project:investigation-observation"]
        self.assertEqual(attempt["relationships"]["informed_by"], [observation["id"]])
        self.assertEqual(attempt["lifecycle_state"], "recorded")
        r = run_cli("validate", store=self.store)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_finding_epistemic_transition_and_contradiction(self):
        self._init()
        finding = self._create(
            "project:finding",
            "retry semantics",
            sample_finding_payload(),
        )
        self.assertEqual(finding["lifecycle_state"], "asserted")
        self.assertEqual(finding["epistemic_status"], "asserted")
        r = run_cli(
            "update",
            "--type",
            finding["record_type"],
            "--id",
            finding["id"],
            "--transition",
            "supported",
            "--expected-revision",
            finding["revision"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        finding = load_json(r.stdout)["record"]
        self.assertEqual(finding["lifecycle_state"], "supported")
        self.assertEqual(finding["epistemic_status"], "supported")
        r = run_cli(
            "contradict",
            "--type",
            finding["record_type"],
            "--id",
            finding["id"],
            "--expected-revision",
            finding["revision"],
            "--subject",
            "retries are idempotent after all",
            "--payload",
            json.dumps(
                sample_finding_payload(
                    claim="vendor retries are idempotent",
                    basis="new sandbox replay",
                )
            ),
            "--transition",
            "disputed",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = load_json(r.stdout)
        original = load_json(
            run_cli(
                "get",
                "--type",
                finding["record_type"],
                "--id",
                finding["id"],
                store=self.store,
            ).stdout
        )
        self.assertEqual(original["lifecycle_state"], "disputed")
        self.assertEqual(original["relationships"]["contradicted_by"], [body["record"]["id"]])
        self.assertEqual(body["record"]["lifecycle_state"], "asserted")
        r = run_cli("validate", store=self.store)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_investigation_summary_view(self):
        self._init()
        question = self._create(
            "project:investigation-question",
            "Are retries idempotent?",
            sample_investigation_question_payload(),
        )
        self._create(
            "project:investigation-observation",
            "429 from vendor",
            sample_observation_payload(),
        )
        self._create("project:finding", "retry semantics", sample_finding_payload())
        contract = load_contract(RESOLVED)
        records = list(Store(self.store).iter_records())
        markdown = generate_view(contract, "project:investigation-summary", records)
        self.assertIn("Investigation Summary", markdown)
        self.assertIn("Are retries idempotent?", markdown)
        self.assertIn("rate limit on retry", markdown)
        self.assertIn("vendor retries are not idempotent", markdown)
        r = run_cli(
            "view",
            "--id",
            "project:investigation-summary",
            "--out",
            "views/investigation-summary.md",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        out = self.store / "views" / "investigation-summary.md"
        self.assertTrue(out.is_file())
        r = run_cli(
            "update",
            "--type",
            question["record_type"],
            "--id",
            question["id"],
            "--transition",
            "answered",
            "--expected-revision",
            question["revision"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_concluded_investigation_bundle(self):
        self._init()
        r = run_cli(
            "capture",
            "--bundle",
            "project:concluded-investigation",
            "--records",
            json.dumps(
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
                        "type": "project:finding",
                        "subject": "retry semantics",
                        "payload": sample_finding_payload(),
                    },
                ]
            ),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(load_json(r.stdout)["records"]), 3)
        r = run_cli("validate", store=self.store)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_correct_rejected_for_current_claim(self):
        self._init()
        from support import sample_position_payload

        rec = self._create(
            "project:current-position",
            "runtime",
            json.loads(sample_position_payload()),
        )
        r = run_cli(
            "correct",
            "--type",
            rec["record_type"],
            "--id",
            rec["id"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 4)
        self.assertIn("not_correctable", r.stdout)


if __name__ == "__main__":
    unittest.main()
