"""Selection clause operators: equals, not_equals, any_of, within."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(RUNTIME.parent.parent / "design" / "contracts"))

from contract import (  # noqa: E402
    ContractError,
    _validate_role_selection,
    record_matches_selection,
)
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


NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)


def _recorded(delta):
    record = _record()
    record["recorded_at"] = (NOW - delta).isoformat()
    return record


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


class RecencyWindowTests(unittest.TestCase):
    def test_24h_window_selects_recent_and_skips_old(self):
        clause = _sel({"field": "recorded_at", "within": "24h"})
        self.assertTrue(record_matches_selection(_recorded(timedelta(hours=1)), clause, now=NOW))
        self.assertFalse(record_matches_selection(_recorded(timedelta(hours=48)), clause, now=NOW))

    def test_window_units_minutes_and_days(self):
        record = _recorded(timedelta(minutes=45))
        self.assertFalse(
            record_matches_selection(record, _sel({"field": "recorded_at", "within": "30m"}), now=NOW)
        )
        self.assertTrue(
            record_matches_selection(record, _sel({"field": "recorded_at", "within": "7d"}), now=NOW)
        )

    def test_record_without_recorded_at_is_skipped(self):
        clause = _sel({"field": "recorded_at", "within": "24h"})
        self.assertFalse(record_matches_selection(_record(), clause, now=NOW))

    def test_now_defaults_to_wall_clock(self):
        record = _record()
        record["recorded_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).replace(microsecond=0).isoformat()
        self.assertTrue(
            record_matches_selection(record, _sel({"field": "recorded_at", "within": "1h"}))
        )

    def test_matcher_rejects_malformed_window(self):
        with self.assertRaises(ContractError):
            record_matches_selection(
                _recorded(timedelta(hours=1)),
                _sel({"field": "recorded_at", "within": "24x"}),
                now=NOW,
            )


MALFORMED_WINDOWS = ("24x", "", "-24h", "0h", "h", "24", 24, None, "1.5h", " 24h")


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
            {"field": "recorded_at", "within": "24h"},
            {"field": "recorded_at", "within": "30m"},
            {"field": "recorded_at", "within": "7d"},
        ):
            validate_selection(_sel(clause), self._candidates(), "role")

    def test_rejects_malformed_window(self):
        for window in MALFORMED_WINDOWS:
            with self.subTest(window=window), self.assertRaises(ResolveError):
                validate_selection(
                    _sel({"field": "recorded_at", "within": window}),
                    self._candidates(),
                    "role",
                )

    def test_within_only_applies_to_recorded_at(self):
        with self.assertRaises(ResolveError):
            validate_selection(
                _sel({"field": "payload.kind", "within": "24h"}),
                self._candidates(),
                "role",
            )

    def test_recorded_at_only_takes_within(self):
        with self.assertRaises(ResolveError):
            validate_selection(
                _sel({"field": "recorded_at", "equals": "2026-09-29T12:00:00+00:00"}),
                self._candidates(),
                "role",
            )

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


class ContractLoadValidationTests(unittest.TestCase):
    OCCUPANT = {"lifecycle": {"states": ["planned", "done"]}, "payload": ["kind"]}

    def _role(self, clause):
        return {"name": "recent", "selection": _sel(clause)}

    def test_accepts_window(self):
        _validate_role_selection(self._role({"field": "recorded_at", "within": "24h"}), self.OCCUPANT)

    def test_rejects_malformed_window(self):
        for window in MALFORMED_WINDOWS:
            with self.subTest(window=window), self.assertRaises(ContractError):
                _validate_role_selection(
                    self._role({"field": "recorded_at", "within": window}), self.OCCUPANT
                )

    def test_rejects_within_on_other_fields(self):
        with self.assertRaises(ContractError):
            _validate_role_selection(
                self._role({"field": "lifecycle_state", "within": "24h"}), self.OCCUPANT
            )


if __name__ == "__main__":
    unittest.main()
