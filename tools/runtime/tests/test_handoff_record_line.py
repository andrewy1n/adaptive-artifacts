"""Regression tests for handoff._record_line's payload allowlisting and links.

requires_payload is a strict allowlist: only the listed fields render, in the
declared order, minus owner/subject (which already render elsewhere in the
line). Everything else in payload -- including a future top-level `body`
field, which never even reaches payload -- must be absent from the rendered
line. Every rendered id is also a Markdown link to the record's file, and
every generated view carries a deterministic store-state digest.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
REPO_ROOT = RUNTIME.parent.parent
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(REPO_ROOT))

from handoff import _record_line, generate_view  # noqa: E402
from paths import type_dir_name  # noqa: E402
from record_file import RECORD_SUFFIX  # noqa: E402


def _expected_link(record_id: str, record_type: str = "demo:thing", store_root: str = ".artifacts") -> str:
    return f"[{record_id}]({store_root}/records/{type_dir_name(record_type)}/{record_id}{RECORD_SUFFIX})"


def _record(record_type="demo:thing", subject="the subject", record_id="rec-1", **payload):
    return {
        "id": record_id,
        "record_type": record_type,
        "subject": subject,
        "lifecycle_state": "open",
        "payload": payload,
    }


def _role(name="thing", occupant="demo:thing", requires_payload=None):
    role = {"name": name, "occupant": occupant, "selection": {"all": []}}
    if requires_payload is not None:
        role["requires_payload"] = requires_payload
    return role


def _contract(view_id, roles, group_by=None, order_by=None):
    view = {"id": view_id, "roles": roles}
    parameters = {}
    if group_by is not None:
        parameters["group_by"] = group_by
    if order_by is not None:
        parameters["order_by"] = order_by
    if parameters:
        view["parameters"] = parameters
    return {"views": [view]}


class RecordLineAllowlistTests(unittest.TestCase):
    def test_only_declared_fields_render_in_declared_order(self):
        record = _record(next="ship it", goal="hit the milestone", extra="unused")
        role = _role(requires_payload=["next", "goal"])
        line = _record_line(record, role)
        self.assertIn("ship it; hit the milestone", line)

    def test_field_outside_requires_payload_is_absent(self):
        record = _record(goal="ship it", secret_note="do not print this")
        role = _role(requires_payload=["goal"])
        line = _record_line(record, role)
        self.assertIn("ship it", line)
        self.assertNotIn("secret_note", line)
        self.assertNotIn("do not print this", line)

    def test_owner_and_subject_still_suppressed_from_summary_even_if_requested(self):
        record = _record(goal="ship it", owner="agent")
        # payload.subject is a distinct decoy from record["subject"] (the bullet
        # label) -- it must not leak into the summary even when requested.
        record["payload"]["subject"] = "payload-subject-value"
        role = _role(requires_payload=["owner", "subject", "goal"])
        line = _record_line(record, role)
        # owner/subject never appear twice: they already render elsewhere in
        # the line (bullet label, id suffix), so the summary body drops them
        # even when a role explicitly lists them.
        self.assertEqual(line.count("agent"), 1)
        self.assertNotIn("payload-subject-value", line)
        self.assertEqual(line.count("the subject"), 1)
        self.assertIn("ship it", line)

    def test_scope_and_blocking_render_when_explicitly_requested(self):
        record = _record(goal="ship it", scope="design/runtime", blocking=True)
        role = _role(requires_payload=["scope", "blocking", "goal"])
        line = _record_line(record, role)
        # scope and blocking have no other home in the line, so an explicit
        # request now overrides the old blanket skip -- unlike owner/subject.
        self.assertIn("design/runtime", line)
        self.assertIn("True", line)
        self.assertIn("ship it", line)

    def test_scope_not_requested_still_absent(self):
        record = _record(goal="ship it", scope="design/runtime")
        role = _role(requires_payload=["goal"])
        line = _record_line(record, role)
        self.assertIn("ship it", line)
        self.assertNotIn("design/runtime", line)

    def test_requested_owner_rendered_in_owner_id_position(self):
        record = _record(goal="ship it", owner="agent")
        role = _role(requires_payload=["goal", "owner"])
        line = _record_line(record, role)
        self.assertIn(f"_(owner: agent, id: {_expected_link('rec-1')})_", line)

    def test_unrequested_owner_is_suppressed_like_any_other_field(self):
        record = _record(goal="ship it", owner="agent")
        role = _role(requires_payload=["goal"])
        line = _record_line(record, role)
        self.assertNotIn("agent", line)

    def test_owner_with_no_summary_falls_back_to_plain_owner_line(self):
        record = _record(owner="agent")
        # scope is requested but has no value on this record -> empty summary
        role = _role(requires_payload=["scope", "owner"])
        line = _record_line(record, role)
        self.assertEqual(line, f"- the subject _(owner: agent, id: {_expected_link('rec-1')})_")

    def test_empty_and_none_fields_suppressed_but_requested_bool_renders(self):
        record = _record(goal="ship it", note="", flag=None, active=True)
        role = _role(requires_payload=["goal", "note", "flag", "active"])
        line = _record_line(record, role)
        self.assertIn("ship it", line)
        # An explicitly requested bool now renders like any other requested
        # field -- suppressing it silently would recreate the "renders
        # nothing" bug this allowlist override is meant to fix.
        self.assertIn("ship it; True", line)

    def test_no_requires_payload_renders_nothing_but_subject_and_id(self):
        record = _record(goal="ship it", scope="design/runtime", note="lots of stuff")
        role = _role()  # no requires_payload key at all
        line = _record_line(record, role)
        self.assertEqual(line, f"- the subject _(id: {_expected_link('rec-1')})_")

    def test_empty_requires_payload_list_also_renders_nothing_but_subject_and_id(self):
        record = _record(goal="ship it", note="lots of stuff")
        role = _role(requires_payload=[])
        line = _record_line(record, role)
        self.assertEqual(line, f"- the subject _(id: {_expected_link('rec-1')})_")

    def test_no_summary_and_no_owner_falls_back_to_bare_subject_line(self):
        record = _record()
        role = _role(requires_payload=["goal"])
        line = _record_line(record, role)
        self.assertEqual(line, f"- the subject _(id: {_expected_link('rec-1')})_")

    def test_id_link_is_relative_not_absolute(self):
        record = _record(goal="ship it")
        role = _role(requires_payload=["goal"])
        line = _record_line(record, role)
        match = re.search(r"id: \[rec-1\]\(([^)]+)\)", line)
        self.assertIsNotNone(match)
        link_target = match.group(1)
        self.assertFalse(link_target.startswith("/"))
        self.assertTrue(link_target.endswith(f"rec-1{RECORD_SUFFIX}"))
        self.assertIn("records/demo__thing/", link_target)

    def test_id_link_honors_custom_store_root(self):
        record = _record(goal="ship it")
        role = _role(requires_payload=["goal"])
        line = _record_line(record, role, store_root="somewhere/else")
        self.assertIn(_expected_link("rec-1", store_root="somewhere/else"), line)
        self.assertNotIn(".artifacts", line)

    def test_large_body_never_leaks_into_rendered_line(self):
        record = _record(goal="ship it", scope="design/runtime")
        record["body"] = "X" * 200_000
        role = _role(requires_payload=["goal", "scope"])
        line = _record_line(record, role)
        self.assertNotIn("X" * 100, line)
        self.assertLess(len(line), 1000)

    def test_large_body_never_leaks_into_generated_view(self):
        record = _record(goal="ship it", scope="design/runtime")
        record["body"] = "X" * 200_000
        role = _role(requires_payload=["goal", "scope"])
        contract = _contract("demo:view", [role])
        markdown = generate_view(contract, "demo:view", [record])
        self.assertNotIn("X" * 100, markdown)


class GenerateViewGroupingAndHeadingsTests(unittest.TestCase):
    def test_grouping_and_headings_unchanged_by_allowlisting(self):
        role = _role(name="thing", requires_payload=["goal"])
        records = [
            _record(subject="a", record_id="rec-a", goal="do a", extra="drop me"),
            _record(subject="b", record_id="rec-b", goal="do b", extra="drop me too"),
        ]
        contract = _contract("demo:view", [role], group_by="subject")
        markdown = generate_view(contract, "demo:view", records)
        self.assertIn("# Demo View", markdown)
        self.assertIn("> Derived view — not authoritative.", markdown)
        self.assertIn("## a", markdown)
        self.assertIn("## b", markdown)
        self.assertIn("### Thing", markdown)
        self.assertIn("do a", markdown)
        self.assertIn("do b", markdown)
        self.assertNotIn("drop me", markdown)

    def test_no_matching_records_message_unchanged(self):
        role = _role(requires_payload=["goal"])
        contract = _contract("demo:view", [role])
        markdown = generate_view(contract, "demo:view", [])
        self.assertIn("_No matching records._", markdown)


def _phase(subject, ordinal=None, phase_id=None, record_type="demo:phase"):
    payload = {} if ordinal is None else {"ordinal": ordinal}
    return {
        "id": phase_id or f"phase-rec-{subject}",
        "record_type": record_type,
        "subject": subject,
        "lifecycle_state": "active",
        "payload": payload,
    }


def _item(phase, record_id, goal="do it"):
    return _record(record_id=record_id, subject=goal, goal=goal, phase=phase)


class GroupOrderingTests(unittest.TestCase):
    def _view(self, records, order_by=None):
        role = _role(name="thing", requires_payload=["goal"])
        contract = _contract("demo:view", [role], group_by="phase", order_by=order_by)
        return generate_view(contract, "demo:view", records)

    def _group_headings(self, markdown):
        return [line[3:] for line in markdown.splitlines() if line.startswith("## ")]

    def test_without_order_by_groups_are_plain_alphabetical(self):
        # This is the bug the feature fixes: "phase-10" sorts before
        # "phase-2" alphabetically even though it should come after.
        records = [
            _phase("phase-2", ordinal=2),
            _phase("phase-10", ordinal=10),
            _item("phase-2", "wi-1"),
            _item("phase-10", "wi-2"),
        ]
        markdown = self._view(records, order_by=None)
        self.assertEqual(self._group_headings(markdown), ["phase-10", "phase-2"])

    def test_ordinal_on_grouping_record_fixes_two_vs_ten(self):
        records = [
            _phase("phase-2", ordinal=2),
            _phase("phase-10", ordinal=10),
            _item("phase-2", "wi-1"),
            _item("phase-10", "wi-2"),
        ]
        markdown = self._view(records, order_by="ordinal")
        self.assertEqual(self._group_headings(markdown), ["phase-2", "phase-10"])

    def test_tied_ordinals_break_alphabetically(self):
        records = [
            _phase("phase-b", ordinal=5),
            _phase("phase-a", ordinal=5),
            _item("phase-b", "wi-1"),
            _item("phase-a", "wi-2"),
        ]
        markdown = self._view(records, order_by="ordinal")
        self.assertEqual(self._group_headings(markdown), ["phase-a", "phase-b"])

    def test_group_with_no_orderable_value_falls_back_after_ordered_groups(self):
        records = [
            _phase("phase-2", ordinal=2),
            _phase("phase-1", ordinal=1),
            _item("phase-2", "wi-1"),
            _item("phase-1", "wi-2"),
            # "phase-unranked" has no matching phase record at all.
            _item("phase-unranked", "wi-3"),
        ]
        markdown = self._view(records, order_by="ordinal")
        self.assertEqual(
            self._group_headings(markdown), ["phase-1", "phase-2", "phase-unranked"]
        )

    def test_non_int_ordinal_value_treated_as_not_orderable(self):
        records = [
            _phase("phase-a", record_type="demo:phase"),
            _item("phase-a", "wi-1"),
        ]
        records[0]["payload"]["ordinal"] = "not-a-number"
        records.append(_phase("phase-b", ordinal=1))
        records.append(_item("phase-b", "wi-2"))
        markdown = self._view(records, order_by="ordinal")
        # phase-b has a real ordinal so it sorts first; phase-a falls back.
        self.assertEqual(self._group_headings(markdown), ["phase-b", "phase-a"])

    def test_within_group_order_is_stable_regardless_of_input_order(self):
        role = _role(name="thing", requires_payload=["goal"])
        contract = _contract("demo:view", [role], group_by="subject")
        a = _record(subject="same", record_id="rec-a", goal="a")
        b = _record(subject="same", record_id="rec-b", goal="b")
        forward = generate_view(contract, "demo:view", [a, b])
        backward = generate_view(contract, "demo:view", [b, a])
        self.assertEqual(forward, backward)
        first_index = forward.index("rec-a")
        second_index = forward.index("rec-b")
        self.assertLess(first_index, second_index)

    def test_two_renders_of_unchanged_store_are_byte_identical(self):
        records = [
            _phase("phase-2", ordinal=2),
            _phase("phase-10", ordinal=10),
            _item("phase-2", "wi-1"),
            _item("phase-10", "wi-2"),
        ]
        first = self._view(list(records), order_by="ordinal")
        second = self._view(list(reversed(records)), order_by="ordinal")
        self.assertEqual(first, second)


class StoreStateProvenanceTests(unittest.TestCase):
    def _view(self, records):
        role = _role(name="thing", requires_payload=["goal"])
        contract = _contract("demo:view", [role])
        return generate_view(contract, "demo:view", records)

    def _digest_line(self, markdown):
        return next(line for line in markdown.splitlines() if line.startswith("> Store state:"))

    def test_store_state_marker_present(self):
        markdown = self._view([_record(goal="ship it")])
        self.assertTrue(any(line.startswith("> Store state:") for line in markdown.splitlines()))

    def test_store_state_marker_deterministic_on_unchanged_store(self):
        records = [_record(record_id="rec-a", goal="ship it")]
        first = self._digest_line(self._view(records))
        second = self._digest_line(self._view([_record(record_id="rec-a", goal="ship it")]))
        self.assertEqual(first, second)

    def test_store_state_marker_changes_when_a_record_changes(self):
        before = self._digest_line(self._view([_record(record_id="rec-a", goal="ship it")]))
        after = self._digest_line(self._view([_record(record_id="rec-a", goal="ship it later")]))
        self.assertNotEqual(before, after)

    def test_store_state_marker_stable_regardless_of_record_order(self):
        a = _record(record_id="rec-a", goal="do a")
        b = _record(record_id="rec-b", goal="do b")
        forward = self._digest_line(self._view([a, b]))
        backward = self._digest_line(self._view([b, a]))
        self.assertEqual(forward, backward)

    def test_store_state_marker_ignores_non_contributing_records(self):
        # A record of a type/selection this view doesn't render shouldn't
        # move the digest -- it can't affect this view's content.
        base = [_record(record_id="rec-a", goal="ship it")]
        unrelated = _record(record_type="other:thing", record_id="rec-z", goal="irrelevant")
        without = self._digest_line(self._view(base))
        with_unrelated = self._digest_line(self._view(base + [unrelated]))
        self.assertEqual(without, with_unrelated)

    def test_store_state_marker_is_a_plain_digest_not_a_timestamp(self):
        digest_line = self._digest_line(self._view([_record(goal="ship it")]))
        value = digest_line.split("Store state: ", 1)[1]
        self.assertRegex(value, r"^sha256:[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
