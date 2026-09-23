"""Every mutation command (create/update/supersede/correct/contradict/capture)
must emit one consistent envelope: {"ok": true, "op": "<verb>", "record": {...}},
with "predecessor" added for ops that retire an old record. Before this, each
command had its own ad hoc shape (e.g. supersede's "old"/"new" keys), which is
what broke a caller's parser."""

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
    sample_investigation_question_payload,
    sample_observation_payload,
    sample_position_payload,
)


class MutationEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".mutation-envelope-test"
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
        body = load_json(r.stdout)
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["op"], "create")
        return body["record"]

    def test_create_envelope(self):
        record = self._create(
            "project:current-position", "runtime", json.loads(sample_position_payload())
        )
        self.assertIn("id", record)

    def test_update_envelope(self):
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
            finding["revision"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = load_json(r.stdout)
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["op"], "update")
        self.assertEqual(body["record"]["lifecycle_state"], "supported")

    def test_supersede_envelope(self):
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
            record["revision"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = load_json(r.stdout)
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["op"], "supersede")
        self.assertNotEqual(body["record"]["id"], record["id"])
        self.assertEqual(body["predecessor"]["id"], record["id"])

    def test_correct_envelope(self):
        record = self._create(
            "project:investigation-observation", "429 from vendor", sample_observation_payload()
        )
        r = run_cli(
            "correct",
            "--type",
            record["record_type"],
            "--id",
            record["id"],
            "--payload",
            json.dumps(sample_observation_payload(what_was_observed="429 then 503")),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = load_json(r.stdout)
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["op"], "correct")
        self.assertNotEqual(body["record"]["id"], record["id"])
        self.assertEqual(body["predecessor"]["id"], record["id"])

    def test_contradict_envelope(self):
        finding = self._create(
            "project:finding", "retry semantics", sample_finding_payload()
        )
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
            json.dumps(sample_finding_payload(claim="vendor retries are idempotent")),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = load_json(r.stdout)
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["op"], "contradict")
        self.assertNotEqual(body["record"]["id"], finding["id"])
        self.assertEqual(body["predecessor"]["id"], finding["id"])

    def test_capture_envelope(self):
        r = run_cli(
            "capture",
            "--bundle",
            "project:concluded-investigation",
            "--records",
            json.dumps(
                [
                    {
                        "type": "project:investigation-question",
                        "subject": "why does retry duplicate orders",
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
        body = load_json(r.stdout)
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["op"], "capture")
        self.assertIn("records", body)


if __name__ == "__main__":
    unittest.main()
