"""Tests for the instruction pattern -- DESIGN.md's base-kind vocabulary names
`instruction` but nothing in design/contracts/ produced it until now."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
TOOLS = RUNTIME.parent
REPO_ROOT = TOOLS.parent
CONTRACTS = REPO_ROOT / "design" / "contracts"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(CONTRACTS))

from resolve import compose_pattern_record, load_catalog  # noqa: E402
from contract import has_trait, is_append_only  # noqa: E402
from validation import validate_store  # noqa: E402


class InstructionPatternTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(CONTRACTS)

    def _record_def(self):
        return compose_pattern_record(
            {
                "name": "assignment",
                "pattern": "instruction",
                "canonical_for": "work handed to an executor",
                "payload": ["procedure", "executor"],
            },
            self.catalog["traits"],
        )

    def test_instruction_pattern_composes_from_entity_and_occurrence(self):
        record_def = self._record_def()
        self.assertEqual(record_def["base_kind"], "instruction")
        self.assertEqual(set(record_def["traits"]), {"entity", "occurrence"})
        self.assertEqual(record_def["lifecycle"]["initial"], "recorded")

    def test_instruction_is_not_a_current_claim(self):
        # This is the property the assignment use case needs: retries and
        # waves must be able to coexist, not overwrite one active instance.
        record_def = self._record_def()
        self.assertFalse(has_trait(record_def, "current-claim"))

    def test_instruction_is_append_only(self):
        # Prescriptive AND append-only: each assignment is a new record, not
        # a mutation of a prior one.
        record_def = self._record_def()
        self.assertTrue(is_append_only(record_def))

    def test_repeated_assignments_to_the_same_subject_coexist(self):
        record_def = self._record_def()
        record_def["id"] = "project:assignment"

        def assignment(record_id: str) -> dict:
            return {
                "id": record_id,
                "record_type": "project:assignment",
                "subject": "retry-the-flaky-upload-step",
                "lifecycle_state": "recorded",
                "payload": {"procedure": "retry with backoff", "executor": "agent"},
                "provenance": {"sources": ["orchestrator"]},
                "time": {"as_of": "2026-09-04T00:00:00+00:00"},
                "revision": f"sha256:{record_id}",
            }

        records = [assignment("rec-wave-1"), assignment("rec-wave-2")]
        contract = {"records": [record_def]}
        errors = validate_store(contract, records)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
