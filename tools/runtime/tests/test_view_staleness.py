"""Tests for view staleness: `view --check` and `hook-stop` must notice when
a rendered view's embedded `Store state: sha256:...` digest no longer matches
the store it was rendered from."""

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
sys.path.insert(0, str(REPO_ROOT / "design" / "contracts"))

from support import git, run_cli  # noqa: E402
from handoff import embedded_view_state_digest, generate_view, view_is_stale  # noqa: E402

SEED = Path("/home/ayin/aa-scratch/seed-artifacts")

EXIT_OK = 0
EXIT_STALE = 2


def _record(record_id, record_type, subject, lifecycle_state, payload, revision=None):
    return {
        "id": record_id,
        "record_type": record_type,
        "subject": subject,
        "lifecycle_state": lifecycle_state,
        "payload": payload,
        "revision": revision or f"sha256:{record_id}",
    }


_CONTRACT = {
    "views": [
        {
            "id": "test:view",
            "parameters": {"group_by": "subject"},
            "roles": [
                {
                    "name": "items",
                    "occupant": "test:item",
                    "selection": {"all": [{"field": "lifecycle_state", "equals": "active"}]},
                    "requires_payload": [],
                }
            ],
        }
    ]
}


class PureFunctionTests(unittest.TestCase):
    def test_a_freshly_generated_view_is_not_stale(self):
        records = [_record("r-1", "test:item", "one", "active", {})]
        rendered = generate_view(_CONTRACT, "test:view", records)
        self.assertFalse(view_is_stale(_CONTRACT, "test:view", records, rendered))

    def test_editing_a_contributing_record_makes_the_view_stale(self):
        records = [_record("r-1", "test:item", "one", "active", {})]
        rendered = generate_view(_CONTRACT, "test:view", records)
        mutated = [_record("r-1", "test:item", "one", "active", {}, revision="sha256:changed")]
        self.assertTrue(view_is_stale(_CONTRACT, "test:view", mutated, rendered))

    def test_adding_a_selected_record_makes_the_view_stale(self):
        records = [_record("r-1", "test:item", "one", "active", {})]
        rendered = generate_view(_CONTRACT, "test:view", records)
        grown = records + [_record("r-2", "test:item", "two", "active", {})]
        self.assertTrue(view_is_stale(_CONTRACT, "test:view", grown, rendered))

    def test_a_hand_edited_file_missing_the_digest_line_is_stale(self):
        records = [_record("r-1", "test:item", "one", "active", {})]
        self.assertTrue(view_is_stale(_CONTRACT, "test:view", records, "# no digest here\n"))

    def test_embedded_digest_extraction_round_trips(self):
        records = [_record("r-1", "test:item", "one", "active", {})]
        rendered = generate_view(_CONTRACT, "test:view", records)
        digest = embedded_view_state_digest(rendered)
        self.assertIsNotNone(digest)
        self.assertTrue(digest.startswith("sha256:"))
        self.assertIsNone(embedded_view_state_digest("no header at all"))


class ViewCheckCliTests(unittest.TestCase):
    """Against the real 717-record fixture, whose `.artifacts/views/*.md`
    are checked in already fresh."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="view-check-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        shutil.copytree(SEED, self.root / ".artifacts")
        git(self.root, "init", "-q")

    def _handoff_path(self) -> Path:
        return self.root / ".artifacts" / "views" / "handoff.md"

    def _create_and_start_a_work_item(self) -> str:
        result = run_cli(
            "create",
            "--type",
            "project:work-item",
            "--subject",
            "a new work item",
            "--payload",
            json.dumps(
                {
                    "title": "prove the view goes stale",
                    "phase": "phase-0-measurement-harness",
                    "kind": "chore",
                    "assignee": "agent",
                    "effort": "S",
                }
            ),
            "--body",
            "## Description\n\nexercise view staleness detection.\n",
            root=self.root,
        )
        body = json.loads(result.stdout)
        self.assertIn("record", body, result.stdout)
        record_id = body["record"]["id"]
        transition = run_cli(
            "update",
            "--type",
            "project:work-item",
            "--id",
            record_id,
            "--transition",
            "in_progress",
            "--expected-revision",
            body["record"]["revision"],
            root=self.root,
        )
        self.assertEqual(transition.returncode, EXIT_OK, transition.stdout + transition.stderr)
        return record_id

    def test_freshly_copied_fixture_checks_as_fresh(self):
        result = run_cli(
            "view", "--id", "project:handoff", "--check", str(self._handoff_path()), root=self.root
        )
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, EXIT_OK, result.stdout)
        self.assertEqual(payload["status"], "fresh")

    def test_a_new_in_progress_work_item_makes_the_handoff_view_stale(self):
        self._create_and_start_a_work_item()
        result = run_cli(
            "view", "--id", "project:handoff", "--check", str(self._handoff_path()), root=self.root
        )
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, EXIT_STALE, result.stdout)
        self.assertEqual(payload["status"], "stale")
        self.assertIn("project:handoff", payload["views"])

    def test_regenerating_the_view_file_clears_the_staleness(self):
        self._create_and_start_a_work_item()
        write = run_cli(
            "view", "--id", "project:handoff", "--out", "views/handoff.md", root=self.root
        )
        self.assertEqual(write.returncode, EXIT_OK, write.stdout + write.stderr)
        result = run_cli(
            "view", "--id", "project:handoff", "--check", str(self._handoff_path()), root=self.root
        )
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, EXIT_OK, result.stdout)
        self.assertEqual(payload["status"], "fresh")


class HookStopStalenessTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="hook-stop-staleness-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        shutil.copytree(SEED, self.root / ".artifacts")
        git(self.root, "init", "-q")

    def test_hook_stop_passes_on_the_freshly_copied_fixture(self):
        result = run_cli("hook-stop", root=self.root)
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, EXIT_OK, result.stdout)
        self.assertEqual(payload["status"], "valid")

    def test_hook_stop_flags_stale_views_after_an_uncaptured_record_change(self):
        create = run_cli(
            "create",
            "--type",
            "project:work-item",
            "--subject",
            "another work item",
            "--payload",
            json.dumps(
                {
                    "title": "leave the view stale on purpose",
                    "phase": "phase-0-measurement-harness",
                    "kind": "chore",
                    "assignee": "agent",
                    "effort": "S",
                }
            ),
            "--body",
            "## Description\n\nexercise hook-stop staleness detection.\n",
            root=self.root,
        )
        created = json.loads(create.stdout)["record"]
        transition = run_cli(
            "update",
            "--type",
            "project:work-item",
            "--id",
            created["id"],
            "--transition",
            "in_progress",
            "--expected-revision",
            created["revision"],
            root=self.root,
        )
        self.assertEqual(transition.returncode, EXIT_OK, transition.stdout + transition.stderr)
        result = run_cli("hook-stop", root=self.root)
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, EXIT_STALE, result.stdout)
        self.assertEqual(payload["status"], "stale_views")
        self.assertIn("project:handoff", payload["views"])


if __name__ == "__main__":
    unittest.main()
