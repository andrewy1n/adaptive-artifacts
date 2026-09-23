"""Tests for the status-view rendering primitives: a role can ask a view to
show a record's lifecycle_state and derive.py fields, and to tally pass/fail
check-run records against it, without requires_payload having to name fields
it structurally can't (lifecycle_state, derived.*) or invent a second
check-run<->work-item link alongside validation.subject_related."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
REPO_ROOT = RUNTIME.parent.parent
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(REPO_ROOT))

from handoff import _record_line, generate_view, live_view_state_digest  # noqa: E402


def _work_item(record_id, subject, lifecycle_state="in_progress", wave=None, ready=None):
    record = {
        "id": record_id,
        "record_type": "project:work-item",
        "subject": subject,
        "lifecycle_state": lifecycle_state,
        "payload": {"title": subject},
    }
    derived = {}
    if wave is not None:
        derived["wave"] = wave
    if ready is not None:
        derived["ready"] = ready
    if derived:
        record["derived"] = derived
    return record


def _check_run(record_id, subject, result):
    return {
        "id": record_id,
        "record_type": "project:check-run",
        "subject": subject,
        "lifecycle_state": "recorded",
        "payload": {"result": result},
    }


def _role(name="work", occupant="project:work-item", requires_payload=None):
    role = {"name": name, "occupant": occupant, "selection": {"all": []}}
    if requires_payload is not None:
        role["requires_payload"] = requires_payload
    return role


def _contract(view_id, roles, **parameters):
    view = {"id": view_id, "roles": roles}
    if parameters:
        view["parameters"] = parameters
    return {"views": [view]}


class RecordLineStatusBitsTests(unittest.TestCase):
    def test_show_lifecycle_state_renders_the_state(self):
        record = _work_item("wi-1", "do-the-thing", lifecycle_state="in_progress")
        role = _role(requires_payload=["title"])
        line = _record_line(record, role, extra_bits=["state: in_progress"])
        self.assertIn("state: in_progress", line)

    def test_extra_bits_join_after_requires_payload_fields(self):
        record = _work_item("wi-1", "do-the-thing")
        role = _role(requires_payload=["title"])
        line = _record_line(record, role, extra_bits=["wave: 2", "ready: True"])
        self.assertIn("do-the-thing; wave: 2; ready: True", line)

    def test_no_extra_bits_is_unchanged_from_before(self):
        record = _work_item("wi-1", "do-the-thing")
        role = _role(requires_payload=["title"])
        self.assertEqual(_record_line(record, role), _record_line(record, role, extra_bits=None))


class GenerateViewStatusParametersTests(unittest.TestCase):
    def test_show_lifecycle_state_parameter_renders_per_record_state(self):
        role = _role(requires_payload=["title"])
        contract = _contract("test:status", [role], show_lifecycle_state=True)
        records = [_work_item("wi-1", "alpha", lifecycle_state="blocked")]
        markdown = generate_view(contract, "test:status", records)
        self.assertIn("state: blocked", markdown)

    def test_show_derived_parameter_renders_requested_derived_fields(self):
        role = _role(requires_payload=["title"])
        contract = _contract("test:status", [role], show_derived=["wave", "ready"])
        records = [_work_item("wi-1", "alpha", wave=1, ready=True)]
        markdown = generate_view(contract, "test:status", records)
        self.assertIn("wave: 1", markdown)
        self.assertIn("ready: True", markdown)

    def test_views_without_the_new_parameters_render_exactly_as_before(self):
        role = _role(requires_payload=["title"])
        plain = _contract("test:status", [role])
        records = [_work_item("wi-1", "alpha", lifecycle_state="blocked", wave=1, ready=True)]
        markdown = generate_view(plain, "test:status", records)
        # "state:"/"wave:" alone would also match the "Store state:" header
        # line, so assert on the values that would only appear as extra bits.
        self.assertNotIn("blocked", markdown)
        self.assertNotIn("wave: 1", markdown)
        self.assertNotIn("ready: True", markdown)

    def test_tally_counts_subject_related_check_runs_by_result(self):
        role = _role(requires_payload=["title"])
        contract = _contract(
            "test:status", [role], tally_source_type="project:check-run"
        )
        records = [
            _work_item("wi-1", "close-the-gap"),
            _check_run("chk-1", "close-the-gap-ac1", "pass"),
            _check_run("chk-2", "close-the-gap-ac2", "fail"),
            _check_run("chk-3", "unrelated-thing-ac1", "fail"),
        ]
        markdown = generate_view(contract, "test:status", records)
        self.assertIn("criteria: 1 pass / 1 fail", markdown)

    def test_tally_result_field_parameter_overrides_the_default_field_name(self):
        role = _role(requires_payload=["title"])
        contract = _contract(
            "test:status",
            [role],
            tally_source_type="project:check-run",
            tally_result_field="outcome",
        )
        records = [
            _work_item("wi-1", "close-the-gap"),
            {
                "id": "chk-1",
                "record_type": "project:check-run",
                "subject": "close-the-gap-ac1",
                "lifecycle_state": "recorded",
                "payload": {"outcome": "error"},
            },
        ]
        markdown = generate_view(contract, "test:status", records)
        self.assertIn("criteria: 0 pass / 1 fail", markdown)

    def test_check_run_records_are_not_rendered_as_their_own_bullets(self):
        # tally_source_type feeds the tally only -- it isn't a role occupant,
        # so a check-run never gets its own summary line in this view.
        role = _role(requires_payload=["title"])
        contract = _contract(
            "test:status", [role], tally_source_type="project:check-run"
        )
        records = [
            _work_item("wi-1", "close-the-gap"),
            _check_run("chk-1", "close-the-gap-ac1", "pass"),
        ]
        markdown = generate_view(contract, "test:status", records)
        self.assertNotIn("chk-1", markdown)


class TallyStalenessTests(unittest.TestCase):
    """A check-run isn't selected by any role, so without folding tally
    records into the digest inputs, editing one would silently desync the
    embedded Store state digest from the rendered tally."""

    def _contract(self):
        role = _role(requires_payload=["title"])
        return _contract("test:status", [role], tally_source_type="project:check-run")

    def test_adding_a_subject_related_check_run_changes_the_live_digest(self):
        contract = self._contract()
        base = [_work_item("wi-1", "close-the-gap")]
        before = live_view_state_digest(contract, "test:status", base)
        grown = base + [_check_run("chk-1", "close-the-gap-ac1", "fail")]
        after = live_view_state_digest(contract, "test:status", grown)
        self.assertNotEqual(before, after)

    def test_editing_an_unrelated_check_run_still_changes_the_live_digest(self):
        # tally_source_type selects by type alone, matching what generate_view
        # actually tallies over -- narrowing the digest to only
        # subject-related check-runs would let an edit to an unrelated one
        # (which still shows up in the store) go undetected.
        contract = self._contract()
        base = [
            _work_item("wi-1", "close-the-gap"),
            _check_run("chk-1", "unrelated-ac1", "pass"),
        ]
        before = live_view_state_digest(contract, "test:status", base)
        mutated = [
            _work_item("wi-1", "close-the-gap"),
            _check_run("chk-1", "unrelated-ac1", "fail"),
        ]
        after = live_view_state_digest(contract, "test:status", mutated)
        self.assertNotEqual(before, after)

    def test_live_digest_matches_a_fresh_render_when_a_tally_is_present(self):
        contract = self._contract()
        records = [
            _work_item("wi-1", "close-the-gap"),
            _check_run("chk-1", "close-the-gap-ac1", "fail"),
        ]
        rendered = generate_view(contract, "test:status", records)
        embedded = next(
            line for line in rendered.splitlines() if line.startswith("> Store state:")
        )
        live = live_view_state_digest(contract, "test:status", records)
        self.assertIn(live, embedded)


if __name__ == "__main__":
    unittest.main()
