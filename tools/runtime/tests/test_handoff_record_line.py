"""Regression tests for handoff._record_line's payload allowlisting.

requires_payload is a strict allowlist: only the listed fields render, in the
declared order, minus the skip set. Everything else in payload -- including a
future top-level `body` field, which never even reaches payload -- must be
absent from the rendered line.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
REPO_ROOT = RUNTIME.parent.parent
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(REPO_ROOT))

from handoff import _record_line, generate_view  # noqa: E402


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


def _contract(view_id, roles, group_by=None):
    view = {"id": view_id, "roles": roles}
    if group_by is not None:
        view["parameters"] = {"group_by": group_by}
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

    def test_skip_fields_still_suppressed_even_if_requested(self):
        record = _record(goal="ship it", scope="design/runtime", blocking=True, owner="agent")
        role = _role(requires_payload=["scope", "blocking", "owner", "goal"])
        line = _record_line(record, role)
        # scope/blocking/owner are always skipped from the summary body,
        # even when a role explicitly lists them.
        self.assertNotIn("design/runtime", line)
        self.assertNotIn("True", line)
        self.assertIn("ship it", line)

    def test_owner_still_rendered_in_owner_id_position(self):
        record = _record(goal="ship it", owner="agent")
        role = _role(requires_payload=["goal"])
        line = _record_line(record, role)
        self.assertIn("_(owner: agent, id: rec-1)_", line)

    def test_owner_with_no_summary_falls_back_to_plain_owner_line(self):
        record = _record(owner="agent")
        role = _role(requires_payload=["scope"])  # scope is skipped -> empty summary
        line = _record_line(record, role)
        self.assertEqual(line, "- the subject _(owner: agent, id: rec-1)_")

    def test_empty_none_bool_fields_suppressed(self):
        record = _record(goal="ship it", note="", flag=None, active=True)
        role = _role(requires_payload=["goal", "note", "flag", "active"])
        line = _record_line(record, role)
        self.assertIn("ship it", line)
        self.assertNotIn("True", line)
        # Only "ship it" should remain as the summary body.
        self.assertIn("**the subject**: ship it ", line)

    def test_no_requires_payload_renders_nothing_but_subject_and_id(self):
        record = _record(goal="ship it", scope="design/runtime", note="lots of stuff")
        role = _role()  # no requires_payload key at all
        line = _record_line(record, role)
        self.assertEqual(line, "- the subject _(id: rec-1)_")

    def test_empty_requires_payload_list_also_renders_nothing_but_subject_and_id(self):
        record = _record(goal="ship it", note="lots of stuff")
        role = _role(requires_payload=[])
        line = _record_line(record, role)
        self.assertEqual(line, "- the subject _(id: rec-1)_")

    def test_no_summary_and_no_owner_falls_back_to_bare_subject_line(self):
        record = _record()
        role = _role(requires_payload=["goal"])
        line = _record_line(record, role)
        self.assertEqual(line, "- the subject _(id: rec-1)_")

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


if __name__ == "__main__":
    unittest.main()
