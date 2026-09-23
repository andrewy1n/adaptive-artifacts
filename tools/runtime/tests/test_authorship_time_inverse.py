"""Tests for writer identity, recorded_at chronology, and the inverse
relationship index (derive.compute_inverse / derived.referenced_by)."""

from __future__ import annotations

import glob
import hashlib
import json
import shutil
import sys
import time
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
)

from query import (  # noqa: E402
    has_inbound,
    order_by_recorded_at,
    within_time_range,
)
from revision import compute_revision  # noqa: E402
from record_file import load_record  # noqa: E402


class _StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".store-test"
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        r = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def _create(self, subject: str, *, extra: list[str] | None = None, env: dict | None = None) -> dict:
        r = run_cli(
            "create",
            "--type",
            "project:finding",
            "--subject",
            subject,
            "--payload",
            json.dumps(sample_finding_payload()),
            *(extra or []),
            store=self.store,
            env=env,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return load_json(r.stdout)["record"]

    def _list(self, *args: str) -> dict:
        r = run_cli("list", *args, store=self.store)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return load_json(r.stdout)


# -- 1. Authorship (identity) ------------------------------------------------


class IdentityResolutionTests(_StoreTestCase):
    def test_default_identity_is_unknown(self):
        record = self._create("no identity given")
        self.assertEqual(record["identity"], "unknown")

    def test_cli_flag_sets_identity(self):
        record = self._create("cli identity", extra=["--identity", "session-a"])
        self.assertEqual(record["identity"], "session-a")

    def test_env_var_sets_identity(self):
        record = self._create("env identity", env={"ARTIFACTS_IDENTITY": "session-env"})
        self.assertEqual(record["identity"], "session-env")

    def test_cli_flag_overrides_env_var(self):
        record = self._create(
            "flag over env",
            extra=["--identity", "session-flag"],
            env={"ARTIFACTS_IDENTITY": "session-env"},
        )
        self.assertEqual(record["identity"], "session-flag")

    def test_identity_is_distinct_from_steward_role(self):
        record = self._create(
            "role vs identity", extra=["--steward", "human", "--identity", "session-a"]
        )
        # project:finding has no required stewardship dimension, so no
        # "stewardship" key is written at all -- identity must not depend on it.
        self.assertNotIn("stewardship", record)
        self.assertEqual(record["identity"], "session-a")

    def test_identity_survives_for_a_type_that_also_has_stewardship(self):
        r = run_cli(
            "create",
            "--type",
            "project:active-goal",
            "--subject",
            "goal with identity",
            "--steward",
            "human",
            "--identity",
            "session-a",
            "--payload",
            json.dumps({"goal": "ship it", "scope": "x"}),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        record = load_json(r.stdout)["record"]
        self.assertEqual(record["identity"], "session-a")
        self.assertEqual(record["stewardship"]["steward"], "human")

    def test_identity_not_inherited_across_contradict(self):
        original = self._create("origin claim", extra=["--identity", "session-a"])
        r = run_cli(
            "contradict",
            "--type",
            "project:finding",
            "--id",
            original["id"],
            "--expected-revision",
            original["revision"],
            "--subject",
            "counter claim subject",
            "--payload",
            json.dumps(sample_finding_payload(claim="counter claim")),
            "--identity",
            "session-b",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        out = load_json(r.stdout)
        self.assertEqual(out["record"]["identity"], "session-b")
        # The original record was also rewritten (relationships bookkeeping);
        # that write is attributed to whoever performed it now, not frozen at
        # session-a forever.
        updated_original = load_json(
            run_cli(
                "get", "--type", "project:finding", "--id", original["id"], store=self.store
            ).stdout
        )
        self.assertEqual(updated_original["identity"], "session-b")

    def test_identity_not_inherited_across_correct(self):
        r = run_cli(
            "create",
            "--type",
            "project:investigation-observation",
            "--subject",
            "an observation",
            "--identity",
            "session-a",
            "--payload",
            json.dumps(
                {
                    "source": "vendor-docs",
                    "observed_time": "2026-09-04T00:00:00+00:00",
                    "environment": "sandbox",
                    "what_was_observed": "rate limit on retry",
                }
            ),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        original = load_json(r.stdout)["record"]
        r = run_cli(
            "correct",
            "--type",
            "project:investigation-observation",
            "--id",
            original["id"],
            "--identity",
            "session-b",
            "--payload",
            json.dumps({"what_was_observed": "corrected observation"}),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        successor = load_json(r.stdout)["record"]
        self.assertEqual(successor["identity"], "session-b")
        self.assertNotEqual(successor["identity"], original["identity"])

    def test_identity_not_inherited_across_supersede(self):
        r = run_cli(
            "create",
            "--type",
            "project:active-goal",
            "--subject",
            "supersede me",
            "--identity",
            "session-a",
            "--payload",
            json.dumps({"goal": "first goal", "scope": "x"}),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        original = load_json(r.stdout)["record"]
        r = run_cli(
            "supersede",
            "--type",
            "project:active-goal",
            "--id",
            original["id"],
            "--expected-revision",
            original["revision"],
            "--identity",
            "session-b",
            "--payload",
            json.dumps({"goal": "second goal", "scope": "x"}),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        out = load_json(r.stdout)
        self.assertEqual(out["record"]["identity"], "session-b")
        old_record = load_json(
            run_cli(
                "get", "--type", "project:active-goal", "--id", original["id"], store=self.store
            ).stdout
        )
        self.assertEqual(old_record["identity"], "session-b")


# -- 2. Time and chronology --------------------------------------------------


class RecordedAtQueryUnitTests(unittest.TestCase):
    def test_within_time_range_no_bounds_matches_everything(self):
        self.assertTrue(within_time_range({}, None, None))

    def test_within_time_range_missing_field_fails_a_bounded_query(self):
        self.assertFalse(within_time_range({}, "2026-01-01T00:00:00+00:00", None))
        self.assertFalse(within_time_range({}, None, "2026-01-01T00:00:00+00:00"))

    def test_within_time_range_respects_bounds(self):
        record = {"recorded_at": "2026-06-01T00:00:00+00:00"}
        self.assertTrue(within_time_range(record, "2026-01-01T00:00:00+00:00", "2026-12-01T00:00:00+00:00"))
        self.assertFalse(within_time_range(record, "2026-07-01T00:00:00+00:00", None))
        self.assertFalse(within_time_range(record, None, "2026-05-01T00:00:00+00:00"))

    def test_order_by_recorded_at_sorts_oldest_first_by_default(self):
        a = {"id": "a", "recorded_at": "2026-03-01T00:00:00+00:00"}
        b = {"id": "b", "recorded_at": "2026-01-01T00:00:00+00:00"}
        c = {"id": "c", "recorded_at": "2026-02-01T00:00:00+00:00"}
        ordered = order_by_recorded_at([a, b, c])
        self.assertEqual([r["id"] for r in ordered], ["b", "c", "a"])

    def test_order_by_recorded_at_missing_field_sorts_first_regardless_of_reverse(self):
        a = {"id": "a", "recorded_at": "2026-01-01T00:00:00+00:00"}
        no_time = {"id": "no-time"}
        self.assertEqual(
            [r["id"] for r in order_by_recorded_at([a, no_time])], ["no-time", "a"]
        )
        self.assertEqual(
            [r["id"] for r in order_by_recorded_at([a, no_time], reverse=True)],
            ["no-time", "a"],
        )


class RecordedAtCliTests(_StoreTestCase):
    def test_created_record_has_recorded_at(self):
        record = self._create("stamped")
        self.assertIsInstance(record.get("recorded_at"), str)
        self.assertTrue(record["recorded_at"])

    def test_recorded_at_bumps_on_transition(self):
        r = run_cli(
            "create",
            "--type",
            "project:continuity-question",
            "--subject",
            "a question",
            "--payload",
            json.dumps({"owner": "agent", "blocking": True, "scope": "x"}),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        record = load_json(r.stdout)["record"]
        first_stamp = record["recorded_at"]
        time.sleep(1.1)
        r = run_cli(
            "update",
            "--type",
            "project:continuity-question",
            "--id",
            record["id"],
            "--transition",
            "answered",
            "--expected-revision",
            record["revision"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        updated = load_json(r.stdout)["record"]
        self.assertGreater(updated["recorded_at"], first_stamp)

    def test_since_and_until_filter_list(self):
        self._create("in range")
        far_future = "2099-01-01T00:00:00+00:00"
        far_past = "2000-01-01T00:00:00+00:00"
        out = self._list("--since", far_future)
        self.assertEqual(out["count"], 0)
        out = self._list("--until", far_past)
        self.assertEqual(out["count"], 0)
        out = self._list("--since", far_past, "--until", far_future)
        self.assertEqual(out["count"], 1)

    def test_order_by_recorded_at_cli(self):
        first = self._create("first")
        time.sleep(1.1)
        second = self._create("second")
        out = self._list("--order-by", "recorded_at", "--full")
        ids = [r["id"] for r in out["records"]]
        self.assertEqual(ids, [first["id"], second["id"]])


# -- 3. Inverse relationship index -------------------------------------------


class InverseIndexUnitTests(unittest.TestCase):
    def test_has_inbound_true_when_present(self):
        record = {"derived": {"referenced_by": {"contradicts": ["rec-a"]}}}
        self.assertTrue(has_inbound(record, "contradicts"))

    def test_has_inbound_false_when_absent(self):
        self.assertFalse(has_inbound({}, "contradicts"))
        record = {"derived": {"referenced_by": {"contradicts": []}}}
        self.assertFalse(has_inbound(record, "contradicts"))
        record = {"derived": {"referenced_by": {"supersedes": ["x"]}}}
        self.assertFalse(has_inbound(record, "contradicts"))


class InverseIndexCliTests(_StoreTestCase):
    def test_list_where_derived_exposes_referenced_by(self):
        target = self._create("the original claim")
        r = run_cli(
            "create",
            "--type",
            "project:finding",
            "--subject",
            "a counter claim",
            "--payload",
            json.dumps(sample_finding_payload(claim="the opposite")),
            "--rel",
            f"contradicts:{target['id']}",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        source = load_json(r.stdout)["record"]

        out = self._list("--type", "project:finding", "--full")
        by_id = {r["id"]: r for r in out["records"]}
        self.assertEqual(
            by_id[target["id"]]["derived"]["referenced_by"], {"contradicts": [source["id"]]}
        )
        self.assertNotIn("derived", by_id[source["id"]])

    def test_has_inbound_filters_list(self):
        target = self._create("target of a contradiction")
        untouched = self._create("nobody points at this")
        r = run_cli(
            "create",
            "--type",
            "project:finding",
            "--subject",
            "the contradictor",
            "--payload",
            json.dumps(sample_finding_payload(claim="disagreement")),
            "--rel",
            f"contradicts:{target['id']}",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

        out = self._list("--has-inbound", "contradicts")
        ids = {r["id"] for r in out["records"]}
        self.assertEqual(ids, {target["id"]})
        self.assertNotIn(untouched["id"], ids)

    def test_has_inbound_with_no_matches_returns_empty(self):
        self._create("no inbound refs at all")
        out = self._list("--has-inbound", "contradicts")
        self.assertEqual(out["count"], 0)


# -- Cross-cutting: backward compatibility -----------------------------------


class BackwardCompatibilityTests(unittest.TestCase):
    """This repo's own live .artifacts store predates identity/recorded_at
    entirely -- every record must still load, validate, and keep its exact
    revision with these fields absent."""

    def test_real_store_records_lack_new_fields_and_still_validate(self):
        paths = sorted(glob.glob(str(REPO_ROOT / ".artifacts" / "records" / "**" / "*.md"), recursive=True))
        self.assertGreater(len(paths), 0)
        revisions = {}
        for path in paths:
            text = Path(path).read_text()
            record = load_record(text, Path(path))
            self.assertNotIn("identity", record, path)
            self.assertNotIn("recorded_at", record, path)
            self.assertEqual(record["revision"], compute_revision(record), path)
            revisions[path] = record["revision"]
        digest = hashlib.sha256(repr(sorted(revisions.items())).encode()).hexdigest()
        self.assertTrue(digest)  # sanity: computed without raising

    def test_real_store_passes_cli_validate(self):
        r = run_cli("validate", store=REPO_ROOT / ".artifacts", root=REPO_ROOT, cwd=REPO_ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = load_json(r.stdout)
        self.assertEqual(out["status"], "valid")
        self.assertGreater(out["records"], 0)

    def test_real_store_list_and_get_still_work_with_no_new_fields(self):
        r = run_cli("list", "--type", "project:finding", store=REPO_ROOT / ".artifacts", root=REPO_ROOT, cwd=REPO_ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = load_json(r.stdout)
        if out["count"]:
            # recorded_at is always present in the summary shape, even as None
            # for a pre-existing record with no such field.
            self.assertIn("recorded_at", out["records"][0])
            self.assertIsNone(out["records"][0]["recorded_at"])


# -- Cross-cutting: determinism -----------------------------------------------


class DeterminismTests(_StoreTestCase):
    """recorded_at is fine to persist (it only changes when real content
    changes, which correctly changes the revision) -- the invariant that must
    hold is that *rendering* never calls the clock, so regenerating an
    unchanged store's views is byte-identical."""

    def test_view_rendering_is_byte_identical_across_regenerations(self):
        self._create("stable content")
        first = run_cli("handoff", store=self.store)
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        time.sleep(1.1)
        second = run_cli("handoff", store=self.store)
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(first.stdout, second.stdout)

    def test_view_command_is_byte_identical_across_regenerations(self):
        self._create("more stable content")
        first = run_cli("view", store=self.store)
        time.sleep(1.1)
        second = run_cli("view", store=self.store)
        self.assertEqual(first.stdout, second.stdout)


if __name__ == "__main__":
    unittest.main()
