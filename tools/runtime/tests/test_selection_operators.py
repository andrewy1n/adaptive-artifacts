"""Selection clause operators: equals, not_equals, any_of."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(RUNTIME.parent.parent / "design" / "contracts"))

from contract import ContractError, record_matches_selection  # noqa: E402
from resolve import ResolveError, validate_selection  # noqa: E402


def _record(state="planned", **payload):
    return {
        "id": "rec-1",
        "record_type": "project:work-item",
        "subject": "a task",
        "lifecycle_state": state,
        "payload": payload,
        "derived": {"ready": True, "wave": 1},
    }


def _sel(*clauses):
    return {"all": list(clauses)}


class MatcherTests(unittest.TestCase):
    def test_equals_unchanged(self):
        clause = {"field": "lifecycle_state", "equals": "planned"}
        self.assertTrue(record_matches_selection(_record("planned"), _sel(clause)))
        self.assertFalse(record_matches_selection(_record("done"), _sel(clause)))

    def test_not_equals_excludes_only_that_state(self):
        clause = {"field": "lifecycle_state", "not_equals": "done"}
        self.assertTrue(record_matches_selection(_record("planned"), _sel(clause)))
        self.assertTrue(record_matches_selection(_record("withdrawn"), _sel(clause)))
        self.assertFalse(record_matches_selection(_record("done"), _sel(clause)))

    def test_any_of_is_set_membership(self):
        clause = {"field": "lifecycle_state", "any_of": ["planned", "in_progress"]}
        self.assertTrue(record_matches_selection(_record("in_progress"), _sel(clause)))
        self.assertFalse(record_matches_selection(_record("withdrawn"), _sel(clause)))

    def test_operators_work_on_payload_and_derived(self):
        record = _record("planned", kind="deliver")
        self.assertTrue(
            record_matches_selection(
                record, _sel({"field": "payload.kind", "any_of": ["deliver", "repair"]})
            )
        )
        self.assertTrue(
            record_matches_selection(
                record, _sel({"field": "derived.ready", "not_equals": False})
            )
        )

    def test_clauses_still_and_together(self):
        record = _record("in_progress", kind="deliver")
        self.assertFalse(
            record_matches_selection(
                record,
                _sel(
                    {"field": "lifecycle_state", "any_of": ["planned", "in_progress"]},
                    {"field": "payload.kind", "equals": "repair"},
                ),
            )
        )

    def test_clause_needs_exactly_one_operator(self):
        for clause in (
            {"field": "lifecycle_state"},
            {"field": "lifecycle_state", "equals": "done", "not_equals": "planned"},
            {"field": "lifecycle_state", "matches": "done"},
        ):
            with self.assertRaises(ContractError):
                record_matches_selection(_record(), _sel(clause))


class ResolveValidationTests(unittest.TestCase):
    def _candidates(self):
        return [
            {
                "id": "project:work-item",
                "lifecycle": {"states": ["planned", "in_progress", "done"]},
                "payload": ["title", "kind"],
            }
        ]

    def test_accepts_each_operator(self):
        for clause in (
            {"field": "lifecycle_state", "equals": "planned"},
            {"field": "lifecycle_state", "not_equals": "done"},
            {"field": "lifecycle_state", "any_of": ["planned", "in_progress"]},
            {"field": "payload.kind", "equals": "deliver"},
            {"field": "derived.ready", "equals": True},
        ):
            validate_selection(_sel(clause), self._candidates(), "role")

    def test_rejects_unknown_state_inside_any_of(self):
        with self.assertRaises(ResolveError):
            validate_selection(
                _sel({"field": "lifecycle_state", "any_of": ["planned", "nope"]}),
                self._candidates(),
                "role",
            )

    def test_any_of_requires_a_list(self):
        with self.assertRaises(ResolveError):
            validate_selection(
                _sel({"field": "lifecycle_state", "any_of": "planned"}),
                self._candidates(),
                "role",
            )

    def test_rejects_unknown_derived_field(self):
        with self.assertRaises(ResolveError):
            validate_selection(
                _sel({"field": "derived.nonsense", "equals": True}),
                self._candidates(),
                "role",
            )


if __name__ == "__main__":
    unittest.main()
