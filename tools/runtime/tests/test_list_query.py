"""Tests for `list`'s payload/subject/body query surface (query.py)."""

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
    sample_finding_payload,
    sample_observation_payload,
)


class ListQueryTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".list-query-test"
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        r = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

        self.retry_finding = self._create(
            "project:finding",
            "retry semantics",
            sample_finding_payload(
                claim="vendor retries are not idempotent",
                basis="sandbox replay 2026-09-04",
            ),
            "--body",
            "## Summary\n\nThe SSH keepalive interval matters for long-lived retries.\n",
        )
        self.timeout_finding = self._create(
            "project:finding",
            "retry timeout",
            sample_finding_payload(
                claim="timeouts are configurable",
                basis="load test 2026-09-10",
            ),
            "--body",
            "No mention of the interval issue here.\n",
        )
        self.observation = self._create(
            "project:investigation-observation",
            "429 from vendor",
            sample_observation_payload(),
        )

    def _create(self, record_type: str, subject: str, payload: dict, *extra: str) -> dict:
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

    def _list(self, *args: str) -> dict:
        r = run_cli("list", *args, store=self.store)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return load_json(r.stdout)

    # -- individual filters -------------------------------------------------

    def test_type_filter_alone(self):
        out = self._list("--type", "project:finding")
        self.assertEqual(out["count"], 2)
        self.assertTrue(all(r["record_type"] == "project:finding" for r in out["records"]))

    def test_state_filter_alone(self):
        out = self._list("--state", "recorded")
        ids = {r["id"] for r in out["records"]}
        self.assertIn(self.observation["id"], ids)
        self.assertNotIn(self.retry_finding["id"], ids)

    def test_where_payload_equality_alone(self):
        out = self._list("--where", "payload.claim=timeouts are configurable")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["records"][0]["id"], self.timeout_finding["id"])

    def test_where_matching_nothing(self):
        out = self._list("--where", "payload.claim=nothing matches this")
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["records"], [])

    def test_subject_exact_match(self):
        out = self._list("--subject", "retry semantics")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["records"][0]["id"], self.retry_finding["id"])

    def test_subject_prefix_match(self):
        out = self._list("--subject", "retry")
        ids = {r["id"] for r in out["records"]}
        self.assertEqual(ids, {self.retry_finding["id"], self.timeout_finding["id"]})

    def test_subject_prefix_excludes_non_matching(self):
        out = self._list("--subject", "429")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["records"][0]["id"], self.observation["id"])

    def test_grep_hits_body_text(self):
        out = self._list("--grep", "keepalive")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["records"][0]["id"], self.retry_finding["id"])
        self.assertIn("keepalive", out["records"][0]["body_excerpt"].lower())

    def test_grep_missing_matches_nothing(self):
        out = self._list("--grep", "no-such-token-anywhere")
        self.assertEqual(out["count"], 0)

    def test_grep_does_not_match_frontmatter_only_text(self):
        # "vendor-docs" lives in payload/provenance, not in any body -- grep must miss it.
        out = self._list("--grep", "vendor-docs")
        self.assertEqual(out["count"], 0)

    # -- combinations ---------------------------------------------------

    def test_combined_type_state_subject_and_where(self):
        out = self._list(
            "--type",
            "project:finding",
            "--state",
            "asserted",
            "--subject",
            "retry",
            "--where",
            "payload.basis=sandbox replay 2026-09-04",
        )
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["records"][0]["id"], self.retry_finding["id"])

    def test_combined_filters_can_exclude_everything(self):
        out = self._list(
            "--type",
            "project:finding",
            "--subject",
            "retry",
            "--grep",
            "no-such-token-anywhere",
        )
        self.assertEqual(out["count"], 0)

    # -- output shape -----------------------------------------------------

    def test_default_output_has_no_full_body(self):
        out = self._list("--type", "project:finding")
        for record in out["records"]:
            self.assertNotIn("body", record)
            if "body_excerpt" in record:
                self.assertLess(len(record["body_excerpt"]), 200)

    def test_full_flag_includes_raw_body(self):
        out = self._list("--type", "project:finding", "--subject", "retry semantics", "--full")
        self.assertEqual(out["count"], 1)
        self.assertIn("body", out["records"][0])
        self.assertIn("keepalive", out["records"][0]["body"])

    def test_invalid_where_flag_is_a_clean_error(self):
        r = run_cli("list", "--where", "not-a-payload-field=x", store=self.store)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["error"], "invalid_query")

    def test_invalid_grep_pattern_is_a_clean_error(self):
        r = run_cli("list", "--grep", "(unclosed", store=self.store)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(load_json(r.stdout)["error"], "invalid_query")


if __name__ == "__main__":
    unittest.main()
