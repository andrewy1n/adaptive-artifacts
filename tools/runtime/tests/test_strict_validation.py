"""Tests for `validate --strict`: warnings for legal-but-suspicious shapes
that plain `validate` lets through."""

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
from contract import contract_digest  # noqa: E402
from validation import validate_strict  # noqa: E402

SEED = Path("/home/ayin/aa-scratch/seed-artifacts")


def _work_item(record_id: str, deps: list[str] | None = None) -> dict:
    return {
        "id": record_id,
        "record_type": "project:work-item",
        "subject": record_id,
        "lifecycle_state": "planned",
        "payload": {},
        "relationships": {"depends_on": deps} if deps else {},
    }


_WORK_ITEM_DEF = {"relationships": ["depends_on"], "payload": []}


class DependencyEdgeCheckTests(unittest.TestCase):
    def test_warns_when_no_record_of_a_dependency_capable_type_has_an_edge(self):
        records = [_work_item("wi-1"), _work_item("wi-2")]
        warnings = validate_strict(records, {"project:work-item": _WORK_ITEM_DEF})
        self.assertEqual(len(warnings), 1)
        self.assertIn("project:work-item", warnings[0])
        self.assertIn("depends_on", warnings[0])

    def test_no_warning_when_at_least_one_record_carries_an_edge(self):
        records = [_work_item("wi-1", deps=["wi-2"]), _work_item("wi-2")]
        warnings = validate_strict(records, {"project:work-item": _WORK_ITEM_DEF})
        self.assertEqual(warnings, [])

    def test_no_warning_for_a_type_that_does_not_declare_depends_on(self):
        records = [_work_item("wi-1")]
        warnings = validate_strict(records, {"project:work-item": {"payload": []}})
        self.assertEqual(warnings, [])


def _record(record_id: str, record_type: str, payload: dict) -> dict:
    return {
        "id": record_id,
        "record_type": record_type,
        "subject": record_id,
        "lifecycle_state": "active",
        "payload": payload,
    }


class ConstantPayloadFieldCheckTests(unittest.TestCase):
    def _defs(self):
        return {"project:item": {"payload": ["effort"]}}

    def test_warns_when_a_field_never_varies(self):
        records = [
            _record(f"r-{n}", "project:item", {"effort": "M"}) for n in range(12)
        ]
        warnings = validate_strict(records, self._defs())
        self.assertEqual(len(warnings), 1)
        self.assertIn("effort", warnings[0])
        self.assertIn("'M'", warnings[0])

    def test_no_warning_when_the_field_varies(self):
        records = [
            _record(f"r-{n}", "project:item", {"effort": "M"}) for n in range(12)
        ]
        records[0]["payload"]["effort"] = "WTC-65641"
        warnings = validate_strict(records, self._defs())
        self.assertEqual(warnings, [])

    def test_no_warning_below_the_population_floor(self):
        records = [
            _record(f"r-{n}", "project:item", {"effort": "M"}) for n in range(3)
        ]
        self.assertEqual(validate_strict(records, self._defs()), [])

    def test_no_warning_with_fewer_than_two_set_values(self):
        records = [_record("r-1", "project:item", {"effort": "M"})]
        warnings = validate_strict(records, self._defs())
        self.assertEqual(warnings, [])

    def test_no_warning_for_a_store_wide_field_shared_across_types(self):
        defs = {
            "project:item": {"payload": ["effort"]},
            "project:other": {"payload": ["effort"]},
        }
        records = [
            _record("r-1", "project:item", {"effort": "WTC-1"}),
            _record("r-2", "project:item", {"effort": "WTC-1"}),
            _record("r-3", "project:other", {"effort": "WTC-1"}),
        ]
        warnings = validate_strict(records, defs)
        self.assertEqual(warnings, [])

    def test_still_warns_when_a_shared_field_name_actually_varies_elsewhere(self):
        defs = {
            "project:item": {"payload": ["phase"]},
            "project:other": {"payload": ["phase"]},
        }
        records = [
            _record(f"r-{n}", "project:item", {"phase": "phase-1"}) for n in range(12)
        ]
        records.append(_record("r-other", "project:other", {"phase": "phase-2"}))
        warnings = validate_strict(records, defs)
        self.assertEqual(len(warnings), 1)
        self.assertIn("project:item", warnings[0])
        self.assertIn("phase", warnings[0])


class TerminalStateFailingCheckTests(unittest.TestCase):
    def _defs(self):
        return {
            "project:work-item": {"payload": []},
            "project:check-run": {"payload": ["result"]},
        }

    def test_warns_when_a_done_item_has_a_subject_related_failing_check(self):
        records = [
            {
                "id": "wi-1",
                "record_type": "project:work-item",
                "subject": "close-the-gap",
                "lifecycle_state": "done",
                "payload": {},
            },
            {
                "id": "chk-1",
                "record_type": "project:check-run",
                "subject": "close-the-gap-ac1",
                "lifecycle_state": "recorded",
                "payload": {"result": "fail"},
            },
        ]
        warnings = validate_strict(records, self._defs())
        self.assertEqual(len(warnings), 1)
        self.assertIn("wi-1", warnings[0])
        self.assertIn("chk-1", warnings[0])

    def test_no_warning_when_the_check_passes(self):
        records = [
            {
                "id": "wi-1",
                "record_type": "project:work-item",
                "subject": "close-the-gap",
                "lifecycle_state": "done",
                "payload": {},
            },
            {
                "id": "chk-1",
                "record_type": "project:check-run",
                "subject": "close-the-gap-ac1",
                "lifecycle_state": "recorded",
                "payload": {"result": "pass"},
            },
        ]
        warnings = validate_strict(records, self._defs())
        self.assertEqual(warnings, [])

    def test_no_warning_when_the_item_is_not_in_a_terminal_success_state(self):
        records = [
            {
                "id": "wi-1",
                "record_type": "project:work-item",
                "subject": "close-the-gap",
                "lifecycle_state": "in_progress",
                "payload": {},
            },
            {
                "id": "chk-1",
                "record_type": "project:check-run",
                "subject": "close-the-gap-ac1",
                "lifecycle_state": "recorded",
                "payload": {"result": "fail"},
            },
        ]
        warnings = validate_strict(records, self._defs())
        self.assertEqual(warnings, [])

    def test_no_warning_when_subjects_are_unrelated(self):
        records = [
            {
                "id": "wi-1",
                "record_type": "project:work-item",
                "subject": "close-the-gap",
                "lifecycle_state": "done",
                "payload": {},
            },
            {
                "id": "chk-1",
                "record_type": "project:check-run",
                "subject": "close-the-other-gap-ac1",
                "lifecycle_state": "recorded",
                "payload": {"result": "fail"},
            },
        ]
        warnings = validate_strict(records, self._defs())
        self.assertEqual(warnings, [])


class StrictCliTests(unittest.TestCase):
    """End-to-end against the real 717-record fixture: strict mode surfaces
    the real failure it was written for, and default `validate` is unchanged."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="strict-validate-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        shutil.copytree(SEED, self.root / ".artifacts")
        git(self.root, "init", "-q")

    def test_plain_validate_is_unaffected_by_strict_mode_existing(self):
        result = run_cli("validate", root=self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "valid")

    def test_strict_flags_the_done_work_items_with_a_failing_check(self):
        result = run_cli("validate", "--strict", root=self.root)
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 5)
        self.assertEqual(payload["status"], "valid_with_warnings")
        joined = "\n".join(payload["warnings"])
        self.assertIn("done", joined)
        self.assertIn("result='fail'", joined)

    def test_strict_does_not_flag_the_store_wide_effort_and_scope_fields(self):
        result = run_cli("validate", "--strict", root=self.root)
        payload = json.loads(result.stdout)
        joined = "\n".join(payload["warnings"])
        self.assertNotIn("field 'effort'", joined)
        self.assertNotIn("field 'scope'", joined)

    def test_strict_does_not_flag_a_field_shared_by_only_two_records(self):
        # Two decisions naming the same phase is what a phase looks like, not
        # an importer writing a constant. Flagging it trains readers to ignore
        # strict output, which is how a gate stops being a gate.
        result = run_cli("validate", "--strict", root=self.root)
        payload = json.loads(result.stdout)
        joined = "\n".join(payload["warnings"])
        self.assertNotIn("project:decision: payload field 'phase'", joined)


if __name__ == "__main__":
    unittest.main()
