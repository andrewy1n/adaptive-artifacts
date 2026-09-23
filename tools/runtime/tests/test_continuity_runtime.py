"""Comprehensive tests for the experimental continuity runtime."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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
    REPO_ROOT,
    RESOLVED,
    load_json,
    make_git_repo,
    run_cli,
    sample_commitment_payload,
    sample_goal_payload,
    sample_next_payload,
    sample_position_payload,
    sample_question_payload,
)
from contract import contract_digest, load_contract  # noqa: E402
from handoff import generate_handoff  # noqa: E402
from record_file import dump_record, load_record  # noqa: E402
from store import Store, StaleWriteError  # noqa: E402
from validation import validate_store  # noqa: E402


class ContinuityRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".continuity-test"
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))

    def _init(self):
        r = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def _create(self, record_type: str, subject: str, payload: str):
        r = run_cli(
            "create",
            "--type",
            record_type,
            "--subject",
            subject,
            "--payload",
            payload,
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return load_json(r.stdout)["record"]

    def test_contract_materialization(self):
        r = run_cli("resolve", root=REPO_ROOT)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        contract = load_contract(RESOLVED)
        self.assertEqual(contract["project"], "adaptive-artifacts")
        ids = [rec["id"] for rec in contract["records"]]
        self.assertIn("project:current-position", ids)
        self.assertIn("project:next-action", ids)
        self.assertIn("project:finding", ids)
        self.assertIn("project:failed-attempt", ids)
        self.assertIn("project:investigation-summary", [view["id"] for view in contract["views"]])

    def test_init_requires_git(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        r = run_cli("init", store=outside / "store", contract=RESOLVED, cwd=outside)
        self.assertEqual(r.returncode, 1)
        self.assertIn("git_context", r.stdout)

    def test_init_allows_store_at_artifacts_root(self):
        store = self.repo / ".artifacts"
        r = run_cli("init", store=store, contract=RESOLVED, root=self.repo)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue((store / "meta.json").is_file())
        self.assertTrue((store / "records").is_dir())

    def test_init_and_validate_empty_store(self):
        self._init()
        r = run_cli("validate", store=self.store)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(load_json(r.stdout)["status"], "valid")

    def test_position_create_and_supersede_lineage(self):
        self._init()
        first = self._create(
            "project:current-position",
            "runtime",
            sample_position_payload(position="v0"),
        )
        r = run_cli(
            "supersede",
            "--type",
            "project:current-position",
            "--id",
            first["id"],
            "--expected-revision",
            first["revision"],
            "--payload",
            sample_position_payload(position="v1"),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = load_json(r.stdout)
        self.assertNotEqual(body["record"]["id"], first["id"])
        old = load_json(
            run_cli(
                "get",
                "--type",
                "project:current-position",
                "--id",
                first["id"],
                store=self.store,
            ).stdout
        )
        self.assertEqual(old["lifecycle_state"], "superseded")
        self.assertEqual(body["record"]["relationships"]["supersedes"], [first["id"]])

    def test_commitment_lifecycle_paths(self):
        self._init()
        rec = self._create(
            "project:active-commitment",
            "runtime",
            sample_commitment_payload(),
        )
        for transition in ("completed",):
            r = run_cli(
                "update",
                "--type",
                "project:active-commitment",
                "--id",
                rec["id"],
                "--transition",
                transition,
                "--expected-revision",
                rec["revision"],
                store=self.store,
            )
            self.assertEqual(r.returncode, 0, r.stdout)
            rec = load_json(r.stdout)["record"]
            self.assertEqual(rec["lifecycle_state"], transition)

        rec2 = self._create(
            "project:active-commitment",
            "other",
            sample_commitment_payload(outcome="cancel me"),
        )
        r = run_cli(
            "update",
            "--type",
            "project:active-commitment",
            "--id",
            rec2["id"],
            "--transition",
            "cancelled",
            "--expected-revision",
            rec2["revision"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 0)

        rec3 = self._create(
            "project:active-commitment",
            "third",
            sample_commitment_payload(outcome="supersede me"),
        )
        r = run_cli(
            "supersede",
            "--type",
            "project:active-commitment",
            "--id",
            rec3["id"],
            "--expected-revision",
            rec3["revision"],
            "--payload",
            sample_commitment_payload(outcome="replacement"),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0)

    def test_question_lifecycle_paths(self):
        self._init()
        rec = self._create(
            "project:continuity-question",
            "How to validate?",
            sample_question_payload(),
        )
        r = run_cli(
            "update",
            "--type",
            "project:continuity-question",
            "--id",
            rec["id"],
            "--transition",
            "answered",
            "--expected-revision",
            rec["revision"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        rec = load_json(r.stdout)["record"]
        self.assertEqual(rec["lifecycle_state"], "answered")

        rec2 = self._create(
            "project:continuity-question",
            "Deferred path?",
            sample_question_payload(),
        )
        paths = ["deferred", "open", "closed"]
        for transition in paths:
            r = run_cli(
                "update",
                "--type",
                "project:continuity-question",
                "--id",
                rec2["id"],
                "--transition",
                transition,
                "--expected-revision",
                rec2["revision"],
                store=self.store,
            )
            self.assertEqual(r.returncode, 0, r.stdout)
            rec2 = load_json(r.stdout)["record"]
        self.assertEqual(rec2["lifecycle_state"], "closed")

    def test_init_pins_contract_digest(self):
        self._init()
        meta = json.loads((self.store / "meta.json").read_text())
        contract = load_contract(RESOLVED)
        self.assertEqual(meta["contract_digest"], contract_digest(contract))

    def test_init_uses_portable_contract_reference_within_repository(self):
        local_contract = self.repo / "resolved-contract.json"
        shutil.copyfile(RESOLVED, local_contract)
        r = run_cli("init", store=self.store, contract=local_contract)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        meta = json.loads((self.store / "meta.json").read_text())
        self.assertEqual(meta["contract"], "resolved-contract.json")

    def test_contract_drift_rejected(self):
        self._init()
        tampered = self.store / "resolved-tampered.json"
        contract = load_contract(RESOLVED)
        contract["project"] = "tampered"
        tampered.write_text(json.dumps(contract, indent=2) + "\n")
        r = run_cli("validate", store=self.store, contract=tampered)
        self.assertEqual(r.returncode, 4)
        self.assertIn("contract_drift", r.stdout)

    def test_unknown_contract_format_rejected_cleanly(self):
        unsupported = self.repo / "unsupported-contract.json"
        contract = load_contract(RESOLVED)
        contract["format"] = "adaptive-artifacts/resolved-contract@99.0.0"
        unsupported.write_text(json.dumps(contract, indent=2) + "\n")
        r = run_cli("init", store=self.store, contract=unsupported)
        self.assertEqual(r.returncode, 1)
        self.assertIn("unsupported resolved contract format", r.stdout)

    def test_malformed_contract_structure_rejected_before_init(self):
        malformed = self.repo / "malformed-contract.json"
        contract = load_contract(RESOLVED)
        del contract["views"]
        malformed.write_text(json.dumps(contract, indent=2) + "\n")
        r = run_cli("init", store=self.store, contract=malformed)
        self.assertEqual(r.returncode, 1)
        self.assertIn("requires record and view lists", r.stdout)
        self.assertFalse((self.store / "meta.json").exists())

    def test_backend_guarantee_mismatch_rejected_before_init(self):
        incompatible = self.repo / "incompatible-contract.json"
        contract = load_contract(RESOLVED)
        contract["backend"]["guarantees"]["writer_model"] = "multi_writer"
        incompatible.write_text(json.dumps(contract, indent=2) + "\n")
        r = run_cli("init", store=self.store, contract=incompatible)
        self.assertEqual(r.returncode, 1)
        self.assertIn("guarantees do not match runtime semantics", r.stdout)

    def test_update_rejects_superseded_transition(self):
        self._init()
        rec = self._create(
            "project:current-position",
            "runtime",
            sample_position_payload(),
        )
        r = run_cli(
            "update",
            "--type",
            "project:current-position",
            "--id",
            rec["id"],
            "--transition",
            "superseded",
            "--expected-revision",
            rec["revision"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 3)
        self.assertIn("use_supersede", r.stdout)

    def test_stale_write_rejected_without_mutation(self):
        self._init()
        rec = self._create(
            "project:continuity-question",
            "How to validate?",
            sample_question_payload(),
        )
        store = Store(self.store)
        original = store.read_record("project:continuity-question", rec["id"])
        tampered = dict(original)
        tampered["payload"]["blocking"] = False
        store.write_record(tampered, expected_revision=rec["revision"])
        r = run_cli(
            "update",
            "--type",
            "project:continuity-question",
            "--id",
            rec["id"],
            "--transition",
            "answered",
            "--expected-revision",
            rec["revision"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 2)
        current = store.read_record("project:continuity-question", rec["id"])
        self.assertEqual(current["lifecycle_state"], "open")
        self.assertFalse(current["payload"]["blocking"])

    def test_orphan_superseded_detected(self):
        self._init()
        rec = self._create(
            "project:current-position",
            "runtime",
            sample_position_payload(),
        )
        store = Store(self.store)
        orphan = dict(store.read_record("project:current-position", rec["id"]))
        orphan["lifecycle_state"] = "superseded"
        store.write_record(orphan, expected_revision=rec["revision"])
        r = run_cli("validate", store=self.store)
        self.assertEqual(r.returncode, 4)
        errors = load_json(r.stdout)["errors"]
        self.assertTrue(any("requires exactly one same-type successor" in e for e in errors))

    def test_multi_step_supersede_chain_valid(self):
        self._init()
        first = self._create(
            "project:current-position",
            "runtime",
            sample_position_payload(position="v0"),
        )
        second = load_json(
            run_cli(
                "supersede",
                "--type",
                "project:current-position",
                "--id",
                first["id"],
                "--expected-revision",
                first["revision"],
                "--payload",
                sample_position_payload(position="v1"),
                store=self.store,
            ).stdout
        )["record"]
        r = run_cli(
            "supersede",
            "--type",
            "project:current-position",
            "--id",
            second["id"],
            "--expected-revision",
            second["revision"],
            "--payload",
            sample_position_payload(position="v2"),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        r = run_cli("validate", store=self.store)
        self.assertEqual(r.returncode, 0)

    def test_commitment_completion_archives_history(self):
        self._init()
        rec = self._create(
            "project:active-commitment",
            "runtime",
            sample_commitment_payload(),
        )
        prior_revision = rec["revision"]
        r = run_cli(
            "update",
            "--type",
            "project:active-commitment",
            "--id",
            rec["id"],
            "--transition",
            "completed",
            "--expected-revision",
            prior_revision,
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        store = Store(self.store)
        history_path = store.history_snapshot_path(
            "project:active-commitment", rec["id"], prior_revision
        )
        self.assertTrue(history_path.is_file())
        snapshot = load_record(history_path.read_text(), history_path)
        self.assertEqual(snapshot["lifecycle_state"], "active")
        self.assertEqual(snapshot["revision"], prior_revision)

    def test_position_supersede_archives_predecessor(self):
        self._init()
        first = self._create(
            "project:current-position",
            "runtime",
            sample_position_payload(position="v0"),
        )
        prior_revision = first["revision"]
        r = run_cli(
            "supersede",
            "--type",
            "project:current-position",
            "--id",
            first["id"],
            "--expected-revision",
            prior_revision,
            "--payload",
            sample_position_payload(position="v1"),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stdout)
        store = Store(self.store)
        history_path = store.history_snapshot_path(
            "project:current-position", first["id"], prior_revision
        )
        self.assertTrue(history_path.is_file())
        snapshot = load_record(history_path.read_text(), history_path)
        self.assertEqual(snapshot["lifecycle_state"], "active")

    def test_tampered_history_fails_validation(self):
        self._init()
        rec = self._create(
            "project:active-commitment",
            "runtime",
            sample_commitment_payload(),
        )
        run_cli(
            "update",
            "--type",
            "project:active-commitment",
            "--id",
            rec["id"],
            "--transition",
            "completed",
            "--expected-revision",
            rec["revision"],
            store=self.store,
        )
        store = Store(self.store)
        for path, _ in store.iter_history():
            data = load_record(path.read_text(), path)
            data["payload"]["outcome"] = "tampered"
            path.write_text(dump_record(data))
            break
        r = run_cli("validate", store=self.store)
        self.assertEqual(r.returncode, 4)
        self.assertTrue(any("history tamper" in e for e in load_json(r.stdout)["errors"]))

    def test_invalid_transition_rejected(self):
        self._init()
        rec = self._create(
            "project:current-position",
            "runtime",
            sample_position_payload(),
        )
        r = run_cli(
            "update",
            "--type",
            "project:current-position",
            "--id",
            rec["id"],
            "--transition",
            "completed",
            "--expected-revision",
            rec["revision"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 3)
        self.assertIn("invalid_transition", r.stdout)

    def test_blocking_must_be_bool(self):
        self._init()
        r = run_cli(
            "create",
            "--type",
            "project:continuity-question",
            "--subject",
            "bad",
            "--payload",
            json.dumps({"owner": "agent", "blocking": "yes"}),
            store=self.store,
        )
        self.assertEqual(r.returncode, 4)

    def test_commitment_requires_scope_payload(self):
        self._init()
        r = run_cli(
            "create",
            "--type",
            "project:active-commitment",
            "--subject",
            "runtime",
            "--payload",
            json.dumps(
                {
                    "actor": "agent",
                    "outcome": "missing scope",
                    "owner": "agent",
                    "effective_time": "2026-09-04T00:00:00+00:00",
                }
            ),
            store=self.store,
        )
        self.assertEqual(r.returncode, 4)
        self.assertIn("missing payload field 'scope'", r.stdout)

    def test_goal_requires_goal_payload(self):
        self._init()
        r = run_cli(
            "create",
            "--type",
            "project:active-goal",
            "--subject",
            "runtime",
            "--payload",
            json.dumps({"scope": "design/runtime"}),
            store=self.store,
        )
        self.assertEqual(r.returncode, 4)
        self.assertIn("missing payload field 'goal'", r.stdout)

    def test_next_requires_next_payload(self):
        self._init()
        r = run_cli(
            "create",
            "--type",
            "project:next-action",
            "--subject",
            "runtime",
            "--payload",
            json.dumps({"scope": "design/runtime"}),
            store=self.store,
        )
        self.assertEqual(r.returncode, 4)
        self.assertIn("missing payload field 'next'", r.stdout)

    def test_revision_tamper_detected(self):
        self._init()
        rec = self._create(
            "project:current-position",
            "runtime",
            sample_position_payload(),
        )
        path = Store(self.store).record_path("project:current-position", rec["id"])
        data = load_record(path.read_text(), path)
        data["payload"]["position"] = "tampered"
        path.write_text(dump_record(data))
        r = run_cli(
            "get",
            "--type",
            "project:current-position",
            "--id",
            rec["id"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("tamper", r.stdout)

    def test_one_active_position_invariant(self):
        self._init()
        self._create("project:current-position", "runtime", sample_position_payload(scope="a"))
        self._create(
            "project:current-position",
            "runtime",
            sample_position_payload(scope="a", position="second"),
        )
        r = run_cli("validate", store=self.store)
        self.assertEqual(r.returncode, 4)
        errors = load_json(r.stdout)["errors"]
        self.assertTrue(any("multiple active" in e and "current-position" in e for e in errors))

    def test_unknown_type_rejected(self):
        self._init()
        r = run_cli(
            "create",
            "--type",
            "delivery:requirement",
            "--subject",
            "nope",
            "--payload",
            "{}",
            store=self.store,
        )
        self.assertEqual(r.returncode, 4)
        self.assertIn("unknown_type", r.stdout)

    def test_handoff_filtering_and_non_authority(self):
        self._init()
        self._create("project:current-position", "runtime", sample_position_payload())
        self._create("project:active-goal", "runtime", sample_goal_payload())
        self._create("project:next-action", "runtime", sample_next_payload())
        self._create("project:active-commitment", "runtime", sample_commitment_payload())
        self._create(
            "project:continuity-question",
            "Blocking?",
            sample_question_payload(blocking=True),
        )
        self._create(
            "project:continuity-question",
            "Non-blocking",
            sample_question_payload(blocking=False),
        )
        contract = load_contract(RESOLVED)
        records = list(Store(self.store).iter_records())
        md = generate_handoff(contract, records)
        self.assertIn("Derived view", md)
        self.assertIn("### Goal", md)
        self.assertIn("keep agents oriented", md)
        self.assertIn("### Next", md)
        self.assertIn("run the dogfood trial", md)
        self.assertIn("Blocking?", md)
        self.assertNotIn("Non-blocking", md)

        out = self.store / "views" / "handoff.md"
        r = run_cli("handoff", "--out", "views/handoff.md", store=self.store)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(out.is_file())

    def test_contract_accepts_views_without_handoff(self):
        contract = load_contract(RESOLVED)
        contract["views"] = [
            view for view in contract["views"] if view["id"] != "project:handoff"
        ]
        path = self.repo / "no-handoff.json"
        path.write_text(json.dumps(contract, indent=2) + "\n")
        loaded = load_contract(path)
        self.assertTrue(
            any(view["id"] == "project:investigation-summary" for view in loaded["views"])
        )

    def test_handoff_selection_comes_from_contract(self):
        contract = load_contract(RESOLVED)
        handoff = next(view for view in contract["views"] if view["id"] == "project:handoff")
        question_role = next(
            role
            for role in handoff["roles"]
            if role["name"] == "blocking-question"
        )
        question_role["selection"]["all"][1]["equals"] = False
        records = [
            {
                "id": "rec-00000000-0000-4000-8000-000000000001",
                "record_type": "project:continuity-question",
                "subject": "Blocking",
                "lifecycle_state": "open",
                "payload": {"owner": "agent", "blocking": True, "scope": "design/runtime"},
            },
            {
                "id": "rec-00000000-0000-4000-8000-000000000002",
                "record_type": "project:continuity-question",
                "subject": "Non-blocking",
                "lifecycle_state": "open",
                "payload": {"owner": "agent", "blocking": False, "scope": "design/runtime"},
            },
        ]
        markdown = generate_handoff(contract, records)
        self.assertNotIn("Blocking _(owner:", markdown)
        self.assertIn("Non-blocking", markdown)

    def test_handoff_excludes_superseded_goal_and_next(self):
        self._init()
        goal = self._create("project:active-goal", "runtime", sample_goal_payload(goal="old goal"))
        nxt = self._create("project:next-action", "runtime", sample_next_payload(next="old next"))
        run_cli(
            "supersede",
            "--type",
            "project:active-goal",
            "--id",
            goal["id"],
            "--expected-revision",
            goal["revision"],
            "--payload",
            sample_goal_payload(goal="new goal"),
            store=self.store,
        )
        run_cli(
            "supersede",
            "--type",
            "project:next-action",
            "--id",
            nxt["id"],
            "--expected-revision",
            nxt["revision"],
            "--payload",
            sample_next_payload(next="new next"),
            store=self.store,
        )
        contract = load_contract(RESOLVED)
        records = list(Store(self.store).iter_records())
        markdown = generate_handoff(contract, records)
        self.assertIn("new goal", markdown)
        self.assertIn("new next", markdown)
        self.assertNotIn("old goal", markdown)
        self.assertNotIn("old next", markdown)

    def test_handoff_output_stays_within_store(self):
        self._init()
        outside = self.store.parent / "outside.md"
        r = run_cli("handoff", "--out", "../outside.md", store=self.store)
        self.assertEqual(r.returncode, 4)
        self.assertIn("unsafe_output_path", r.stdout)
        self.assertFalse(outside.exists())

    def test_hook_adapters(self):
        self._init()
        self._create("project:current-position", "runtime", sample_position_payload())
        start = run_cli("hook-start", store=self.store)
        self.assertEqual(start.returncode, 0)
        body = load_json(start.stdout)
        self.assertIn("handoff", body)
        self.assertTrue(body["derived"])
        stop = run_cli("hook-stop", store=self.store)
        self.assertEqual(stop.returncode, 0)
        self.assertEqual(load_json(stop.stdout)["status"], "valid")

    def test_hooks_do_not_mutate_records(self):
        self._init()
        rec = self._create(
            "project:current-position",
            "runtime",
            sample_position_payload(),
        )
        before = Store(self.store).read_record("project:current-position", rec["id"])
        run_cli("hook-start", store=self.store)
        run_cli("hook-stop", store=self.store)
        after = Store(self.store).read_record("project:current-position", rec["id"])
        self.assertEqual(before, after)

    def test_store_module_stale_write(self):
        self._init()
        store = Store(self.store)
        record_id = store.new_id()
        record = {
            "id": record_id,
            "record_type": "project:current-position",
            "base_kind": "claim",
            "subject": "x",
            "stewardship": {"steward": "agent"},
            "payload": {"position": "p", "scope": "s"},
            "lifecycle_state": "active",
            "relationships": {},
            "revision": "",
            "epistemic_status": "asserted",
            "time": {"as_of": "2026-09-04T00:00:00+00:00"},
        }
        stored = store.create_record(record)
        with self.assertRaises(StaleWriteError):
            store.write_record(stored, expected_revision="sha256:dead")

    def test_create_requires_initialized_store(self):
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
        self.assertEqual(r.returncode, 1)
        self.assertIn("store_not_ready", r.stdout)

    def test_get_list_require_init_and_contract_binding(self):
        self._init()
        rec = self._create(
            "project:current-position",
            "runtime",
            sample_position_payload(),
        )
        r = run_cli(
            "get",
            "--type",
            "project:current-position",
            "--id",
            rec["id"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 0)
        tampered = self.store / "resolved-tampered.json"
        contract = load_contract(RESOLVED)
        contract["project"] = "tampered"
        tampered.write_text(json.dumps(contract, indent=2) + "\n")
        r = run_cli(
            "list",
            store=self.store,
            contract=tampered,
        )
        self.assertEqual(r.returncode, 4)
        self.assertIn("contract_drift", r.stdout)

    def test_partial_store_without_meta_rejected(self):
        self.store.mkdir(parents=True)
        records = self.store / "records" / "continuity__current-position"
        records.mkdir(parents=True)
        (records / "rec-00000000-0000-4000-8000-000000000001.md").write_text("{}")
        r = run_cli("validate", store=self.store)
        self.assertEqual(r.returncode, 1)
        self.assertIn("store_not_ready", r.stdout)

    def test_hook_start_absent_skips_partial_errors(self):
        absent = run_cli("hook-start", store=self.store / "missing")
        self.assertEqual(absent.returncode, 0)
        self.assertIn("store not initialized", absent.stdout)

        self.store.mkdir(parents=True)
        records = self.store / "records" / "continuity__current-position"
        records.mkdir(parents=True)
        (records / "rec-00000000-0000-4000-8000-000000000002.md").write_text("{}")
        partial = run_cli("hook-start", store=self.store)
        self.assertEqual(partial.returncode, 1)
        self.assertIn("store_not_ready", partial.stdout)

    def test_init_idempotent_same_contract(self):
        self._init()
        r = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(load_json(r.stdout)["status"], "already_initialized")

    def test_init_rejects_contract_rebind(self):
        self._init()
        other = self.store / "other-contract.json"
        contract = load_contract(RESOLVED)
        contract["project"] = "other"
        other.write_text(json.dumps(contract, indent=2) + "\n")
        r = run_cli("init", store=self.store, contract=other)
        self.assertEqual(r.returncode, 1)
        self.assertIn("init_rejected", r.stdout)

    def test_unsafe_record_type_and_id_rejected(self):
        self._init()
        rec = self._create(
            "project:current-position",
            "runtime",
            sample_position_payload(),
        )
        for unsafe_type in ("../escape", "bad/type", "project:bad/name"):
            r = run_cli(
                "get",
                "--type",
                unsafe_type,
                "--id",
                rec["id"],
                store=self.store,
            )
            self.assertEqual(r.returncode, 1, unsafe_type)
            self.assertTrue(
                "unsafe" in r.stdout.lower() or "invalid" in r.stdout.lower(),
                r.stdout,
            )
        r = run_cli(
            "get",
            "--type",
            "project:current-position",
            "--id",
            "../escape",
            store=self.store,
        )
        self.assertEqual(r.returncode, 1)
        self.assertTrue(
            "unsafe" in r.stdout.lower() or "invalid" in r.stdout.lower(),
            r.stdout,
        )

    def test_history_archive_retry_idempotent(self):
        self._init()
        rec = self._create(
            "project:active-commitment",
            "runtime",
            sample_commitment_payload(),
        )
        store = Store(self.store)
        contract = load_contract(RESOLVED)
        store.require_initialized(contract)
        live = store.read_record("project:active-commitment", rec["id"])
        store.archive_history(live)
        store.archive_history(live)
        path = store.history_snapshot_path(
            "project:active-commitment", rec["id"], live["revision"]
        )
        self.assertTrue(path.is_file())

    def test_rehashed_history_path_mismatch_fails_validation(self):
        self._init()
        rec = self._create(
            "project:active-commitment",
            "runtime",
            sample_commitment_payload(),
        )
        run_cli(
            "update",
            "--type",
            "project:active-commitment",
            "--id",
            rec["id"],
            "--transition",
            "completed",
            "--expected-revision",
            rec["revision"],
            store=self.store,
        )
        store = Store(self.store)
        for path, snapshot in store.iter_history():
            snapshot["payload"]["outcome"] = "changed"
            from revision import compute_revision

            snapshot["revision"] = compute_revision(snapshot)
            path.write_text(dump_record(snapshot))
            break
        r = run_cli("validate", store=self.store)
        self.assertEqual(r.returncode, 4)
        errors = load_json(r.stdout)["errors"]
        self.assertTrue(
            any("revision filename mismatch" in e or "history tamper" in e for e in errors)
        )

    def test_malformed_record_json_reports_validation_error(self):
        self._init()
        rec = self._create(
            "project:current-position",
            "runtime",
            sample_position_payload(),
        )
        path = Store(self.store).record_path("project:current-position", rec["id"])
        path.write_text("{not-json")
        r = run_cli("validate", store=self.store)
        self.assertEqual(r.returncode, 4)
        self.assertTrue(
            any("malformed record file" in e for e in load_json(r.stdout)["errors"])
        )


if __name__ == "__main__":
    unittest.main()
