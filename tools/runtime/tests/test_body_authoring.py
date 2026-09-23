"""Tests for --body / --body-file authoring across every record-writing command."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
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
    sample_commitment_payload,
    sample_finding_payload,
    sample_observation_payload,
    sample_position_payload,
)
from record_file import normalize_body  # noqa: E402
from revision import compute_revision  # noqa: E402

RICH_BODY = (
    "## Summary\n"
    "\n"
    "This finding rests on a `retry` budget and a couple of links:\n"
    "[docs](https://example.test/docs).\n"
    "\n"
    "---\n"
    "\n"
    "```python\n"
    "def f(x):\n"
    "    return x + 1\n"
    "```\n"
    "\n"
    "## Details\n"
    "\n"
    "More literal --- lines below.\n"
    "---\n"
)


class BodyAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".body-authoring-test"
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        r = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def _write_temp_file(self, content: str) -> Path:
        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, dir=str(self.repo)
        )
        handle.write(content)
        handle.close()
        path = Path(handle.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

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

    def _get(self, record_type: str, record_id: str) -> dict:
        r = run_cli("get", "--type", record_type, "--id", record_id, store=self.store)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return load_json(r.stdout)

    # -- create ---------------------------------------------------------

    def test_create_with_inline_body(self):
        rec = self._create(
            "project:current-position",
            "runtime",
            json.loads(sample_position_payload()),
            "--body",
            "hello world",
        )
        self.assertEqual(rec["body"], "hello world\n")

    def test_create_with_body_file(self):
        path = self._write_temp_file(RICH_BODY)
        rec = self._create(
            "project:current-position",
            "runtime",
            json.loads(sample_position_payload()),
            "--body-file",
            str(path),
        )
        self.assertEqual(rec["body"], normalize_body(RICH_BODY))

    def test_body_and_body_file_together_is_an_error(self):
        path = self._write_temp_file("from file")
        r = run_cli(
            "create",
            "--type",
            "project:current-position",
            "--subject",
            "runtime",
            "--payload",
            sample_position_payload(),
            "--body",
            "inline",
            "--body-file",
            str(path),
            store=self.store,
        )
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["error"], "invalid_body")

    def test_missing_body_file_gives_clean_error_not_traceback(self):
        r = run_cli(
            "create",
            "--type",
            "project:current-position",
            "--subject",
            "runtime",
            "--payload",
            sample_position_payload(),
            "--body-file",
            str(self.repo / "does-not-exist.md"),
            store=self.store,
        )
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["error"], "invalid_body")
        self.assertNotIn("Traceback", r.stderr)

    def test_no_body_flags_hashes_identically_to_pre_body_behavior(self):
        rec = self._create(
            "project:current-position",
            "runtime",
            json.loads(sample_position_payload()),
        )
        self.assertEqual(rec["body"], "")
        without_body_key = dict(rec)
        del without_body_key["body"]
        self.assertEqual(compute_revision(rec), compute_revision(without_body_key))

    def test_body_round_trips_through_create_and_get(self):
        path = self._write_temp_file(RICH_BODY)
        created = self._create(
            "project:finding",
            "retry semantics",
            sample_finding_payload(),
            "--body-file",
            str(path),
        )
        fetched = self._get(created["record_type"], created["id"])
        self.assertEqual(fetched["body"], normalize_body(RICH_BODY))
        self.assertEqual(fetched, created)

    # -- update -----------------------------------------------------------

    def test_update_without_body_flag_keeps_existing_body(self):
        rec = self._create(
            "project:active-commitment",
            "runtime",
            json.loads(sample_commitment_payload()),
            "--body",
            "original reasoning",
        )
        r = run_cli(
            "update",
            "--type",
            rec["record_type"],
            "--id",
            rec["id"],
            "--transition",
            "completed",
            "--expected-revision",
            rec["revision"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        updated = load_json(r.stdout)["record"]
        self.assertEqual(updated["body"], "original reasoning\n")

    def test_update_with_body_replaces_it(self):
        rec = self._create(
            "project:active-commitment",
            "runtime",
            json.loads(sample_commitment_payload()),
            "--body",
            "original reasoning",
        )
        r = run_cli(
            "update",
            "--type",
            rec["record_type"],
            "--id",
            rec["id"],
            "--transition",
            "completed",
            "--expected-revision",
            rec["revision"],
            "--body",
            "revised reasoning",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["record"]["body"], "revised reasoning\n")

    def test_update_with_empty_body_clears_it(self):
        rec = self._create(
            "project:active-commitment",
            "runtime",
            json.loads(sample_commitment_payload()),
            "--body",
            "original reasoning",
        )
        r = run_cli(
            "update",
            "--type",
            rec["record_type"],
            "--id",
            rec["id"],
            "--transition",
            "completed",
            "--expected-revision",
            rec["revision"],
            "--body",
            "",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["record"]["body"], "")

    # -- supersede ----------------------------------------------------------

    def test_supersede_without_body_flag_carries_body_forward(self):
        rec = self._create(
            "project:current-position",
            "runtime",
            json.loads(sample_position_payload(position="v0")),
            "--body",
            "why v0",
        )
        r = run_cli(
            "supersede",
            "--type",
            rec["record_type"],
            "--id",
            rec["id"],
            "--expected-revision",
            rec["revision"],
            "--payload",
            sample_position_payload(position="v1"),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        successor = load_json(r.stdout)["record"]
        self.assertEqual(successor["body"], "why v0\n")

    def test_supersede_with_body_replaces_it(self):
        rec = self._create(
            "project:current-position",
            "runtime",
            json.loads(sample_position_payload(position="v0")),
            "--body",
            "why v0",
        )
        r = run_cli(
            "supersede",
            "--type",
            rec["record_type"],
            "--id",
            rec["id"],
            "--expected-revision",
            rec["revision"],
            "--payload",
            sample_position_payload(position="v1"),
            "--body",
            "why v1",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["record"]["body"], "why v1\n")

    def test_supersede_with_empty_body_clears_it(self):
        rec = self._create(
            "project:current-position",
            "runtime",
            json.loads(sample_position_payload(position="v0")),
            "--body",
            "why v0",
        )
        r = run_cli(
            "supersede",
            "--type",
            rec["record_type"],
            "--id",
            rec["id"],
            "--expected-revision",
            rec["revision"],
            "--payload",
            sample_position_payload(position="v1"),
            "--body",
            "",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["record"]["body"], "")

    # -- correct --------------------------------------------------------

    def test_correct_without_body_flag_carries_body_forward(self):
        rec = self._create(
            "project:investigation-observation",
            "429 from vendor",
            sample_observation_payload(),
            "--body",
            "raw log excerpt",
        )
        r = run_cli(
            "correct",
            "--type",
            rec["record_type"],
            "--id",
            rec["id"],
            "--payload",
            json.dumps(sample_observation_payload(what_was_observed="429 then 503")),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["record"]["body"], "raw log excerpt\n")

    def test_correct_with_body_replaces_it(self):
        rec = self._create(
            "project:investigation-observation",
            "429 from vendor",
            sample_observation_payload(),
            "--body",
            "raw log excerpt",
        )
        r = run_cli(
            "correct",
            "--type",
            rec["record_type"],
            "--id",
            rec["id"],
            "--payload",
            json.dumps(sample_observation_payload(what_was_observed="429 then 503")),
            "--body",
            "corrected log excerpt",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["record"]["body"], "corrected log excerpt\n")

    def test_correct_with_empty_body_clears_it(self):
        rec = self._create(
            "project:investigation-observation",
            "429 from vendor",
            sample_observation_payload(),
            "--body",
            "raw log excerpt",
        )
        r = run_cli(
            "correct",
            "--type",
            rec["record_type"],
            "--id",
            rec["id"],
            "--payload",
            json.dumps(sample_observation_payload(what_was_observed="429 then 503")),
            "--body",
            "",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["record"]["body"], "")

    # -- contradict -------------------------------------------------------

    def test_contradict_without_body_flag_starts_empty(self):
        finding = self._create(
            "project:finding",
            "retry semantics",
            sample_finding_payload(),
            "--body",
            "original argument",
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
        self.assertEqual(load_json(r.stdout)["record"]["body"], "")

    def test_contradict_with_body_replaces_it(self):
        finding = self._create(
            "project:finding",
            "retry semantics",
            sample_finding_payload(),
            "--body",
            "original argument",
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
            "--body",
            "counter-argument",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["record"]["body"], "counter-argument\n")

    def test_contradict_with_empty_body_clears_it(self):
        finding = self._create(
            "project:finding",
            "retry semantics",
            sample_finding_payload(),
            "--body",
            "original argument",
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
            "--body",
            "",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["record"]["body"], "")

    # -- capture ----------------------------------------------------------

    def test_capture_with_per_record_bodies(self):
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
                        "body": "why we tried this",
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
        self.assertEqual(records["project:failed-attempt"]["body"], "why we tried this\n")
        self.assertEqual(records["project:investigation-observation"]["body"], "")


if __name__ == "__main__":
    unittest.main()
