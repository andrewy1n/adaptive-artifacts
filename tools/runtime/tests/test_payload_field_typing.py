"""Tests for payload_enum, the lightweight typing extension to the
payload_references idiom: a declared field may be a reference (payload_references,
existing), an enum (payload_enum, this), or free text (no declaration)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
REPO_ROOT = RUNTIME.parent.parent
CONTRACTS = REPO_ROOT / "design" / "contracts"

sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(CONTRACTS))

from resolve import ResolveError, compose_pattern_record, load_catalog  # noqa: E402
from validation import ValidationError, validate_payload  # noqa: E402


def _record_def(field="kind", allowed=("deliver", "chore")):
    return {"payload": ["subject", field], "payload_enum": {field: list(allowed)}}


def _record(value):
    return {"id": "rec-1", "payload": {"kind": value}}


class PayloadEnumValidationTests(unittest.TestCase):
    def test_allowed_value_passes(self):
        validate_payload(_record_def(), _record("deliver"))

    def test_value_outside_the_enum_fails_and_names_field_value_and_record(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_payload(_record_def(), _record("WTC-65641"))
        message = str(ctx.exception)
        self.assertIn("rec-1", message)
        self.assertIn("kind", message)
        self.assertIn("WTC-65641", message)

    def test_empty_string_is_treated_as_unset_not_a_violation(self):
        validate_payload(_record_def(), _record(""))

    def test_field_missing_entirely_is_not_a_violation(self):
        record_def = {
            "payload": ["subject", "kind"],
            "optional_payload": ["kind"],
            "payload_enum": {"kind": ["deliver", "chore"]},
        }
        validate_payload(record_def, {"id": "rec-1", "payload": {}})

    def test_the_motivating_case_t_shirt_size_and_free_text_cannot_both_be_valid(self):
        record_def = {"payload": ["subject", "effort"], "payload_enum": {"effort": ["S", "M", "L"]}}
        validate_payload(record_def, {"id": "rec-1", "payload": {"effort": "M"}})
        with self.assertRaises(ValidationError):
            validate_payload(record_def, {"id": "rec-2", "payload": {"effort": "WTC-65641"}})


class PayloadEnumResolutionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(CONTRACTS)

    def _pattern_record(self, **kwargs):
        base = {
            "name": "work-item",
            "pattern": "task",
            "canonical_for": "test task",
            "payload": ["kind"],
            "payload_enum": {"kind": ["deliver", "chore"]},
        }
        base.update(kwargs)
        return compose_pattern_record(base, self.catalog["traits"])

    def test_composed_record_carries_payload_enum(self):
        record_def = self._pattern_record()
        self.assertEqual(record_def["payload_enum"], {"kind": ["deliver", "chore"]})

    def test_declaring_an_enum_for_a_field_not_in_payload_is_rejected(self):
        with self.assertRaises(ResolveError):
            self._pattern_record(payload=[], payload_enum={"kind": ["deliver"]})

    def test_declaring_an_enum_with_no_values_is_rejected(self):
        with self.assertRaises(ResolveError):
            self._pattern_record(payload_enum={"kind": []})


if __name__ == "__main__":
    unittest.main()
