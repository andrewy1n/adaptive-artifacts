"""Tests for the staged-progress trait and the finding/decision contradiction edges."""

from __future__ import annotations

import json
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

from resolve import (  # noqa: E402
    FIXTURE_DIR,
    ResolveError,
    compose_pattern_record,
    compose_record,
    load_catalog,
    resolve_fixture,
    resolve_project,
)
from contract import allowed_transition  # noqa: E402
from validation import validate_relationships  # noqa: E402


class StagedProgressTraitTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(CONTRACTS)
        self.record = compose_record(
            {
                "name": "work-item",
                "traits": ["entity", "stewarded", "staged-progress"],
                "base_kind": "task",
            },
            "test",
            self.catalog["traits"],
        )

    def test_composes_with_expected_lifecycle(self):
        lifecycle = self.record["lifecycle"]
        self.assertEqual(lifecycle["initial"], "planned")
        self.assertEqual(
            set(lifecycle["states"]),
            {"planned", "in_progress", "done", "withdrawn", "superseded"},
        )

    def test_legal_transitions_accepted(self):
        legal = [
            ("planned", "in_progress"),
            ("planned", "withdrawn"),
            ("planned", "superseded"),
            ("in_progress", "done"),
            ("in_progress", "withdrawn"),
            ("in_progress", "superseded"),
            ("done", "superseded"),
        ]
        for src, dest in legal:
            with self.subTest(src=src, dest=dest):
                self.assertTrue(allowed_transition(self.record, src, dest))

    def test_illegal_transitions_rejected(self):
        illegal = [
            ("done", "in_progress"),
            ("withdrawn", "in_progress"),
            ("planned", "done"),
            ("superseded", "planned"),
        ]
        for src, dest in illegal:
            with self.subTest(src=src, dest=dest):
                self.assertFalse(allowed_transition(self.record, src, dest))

    def test_withdrawn_and_done_are_distinguishable_terminal_states(self):
        transitions = self.record["lifecycle"]["transitions"]
        # Both are reachable dead ends today via a single boolean flag upstream;
        # here they must differ in what happens next.
        self.assertEqual(transitions.get("withdrawn", []), [])
        self.assertEqual(transitions.get("done", []), ["superseded"])
        self.assertNotEqual(transitions.get("withdrawn", []), transitions.get("done", []))

    def test_depends_on_relationship_advertised(self):
        self.assertIn("depends_on", self.record["relationships"])

    def test_depends_on_accepted_by_relationship_validation(self):
        record = {
            "id": "test:work-item#1",
            "relationships": {"depends_on": ["test:work-item#2"]},
        }
        validate_relationships(
            self.record, record, {"test:work-item#1", "test:work-item#2"}
        )

    def test_composing_with_another_lifecycle_trait_is_rejected(self):
        with self.assertRaises(ResolveError):
            compose_record(
                {
                    "name": "conflicted",
                    "traits": ["entity", "stewarded", "staged-progress", "current-claim"],
                },
                "test",
                self.catalog["traits"],
            )


class TaskPhasePatternTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(CONTRACTS)

    def test_task_pattern_composes_staged_progress(self):
        record = compose_pattern_record(
            {
                "name": "task-1",
                "pattern": "task",
                "canonical_for": "test task",
                "payload": [],
            },
            self.catalog["traits"],
        )
        self.assertEqual(record["base_kind"], "task")
        self.assertEqual(record["lifecycle"]["initial"], "planned")
        self.assertIn("depends_on", record["relationships"])

    def test_phase_pattern_composes_staged_progress(self):
        record = compose_pattern_record(
            {
                "name": "phase-1",
                "pattern": "phase",
                "canonical_for": "test phase",
                "payload": [],
            },
            self.catalog["traits"],
        )
        self.assertEqual(record["base_kind"], "phase")
        self.assertEqual(record["lifecycle"]["initial"], "planned")
        self.assertIn("depends_on", record["relationships"])


class ContradictionEdgeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(CONTRACTS)

    def _finding(self):
        return compose_pattern_record(
            {
                "name": "finding-1",
                "pattern": "finding",
                "canonical_for": "test finding",
                "payload": ["claim", "basis"],
            },
            self.catalog["traits"],
        )

    def _decision(self):
        return compose_pattern_record(
            {
                "name": "decision-1",
                "pattern": "decision",
                "canonical_for": "test decision",
                "payload": ["choice"],
            },
            self.catalog["traits"],
        )

    def test_finding_advertises_outbound_contradicts(self):
        self.assertIn("contradicts", self._finding()["relationships"])

    def test_decision_advertises_contradicted_by(self):
        self.assertIn("contradicted_by", self._decision()["relationships"])

    def test_contradiction_validates_from_finding_to_decision(self):
        finding = self._finding()
        record = {
            "id": "project:finding-1",
            "relationships": {"contradicts": ["project:decision-1"]},
        }
        validate_relationships(
            finding, record, {"project:finding-1", "project:decision-1"}
        )

    def test_contradiction_validates_from_decision_to_finding(self):
        decision = self._decision()
        record = {
            "id": "project:decision-1",
            "relationships": {"contradicted_by": ["project:finding-1"]},
        }
        validate_relationships(
            decision, record, {"project:finding-1", "project:decision-1"}
        )

    def test_unrelated_current_claim_patterns_do_not_gain_contradicted_by(self):
        replica = compose_pattern_record(
            {
                "name": "replica-1",
                "pattern": "replica",
                "replica_of": "some-source",
                "payload": [],
            },
            self.catalog["traits"],
        )
        definition = compose_pattern_record(
            {
                "name": "definition-1",
                "pattern": "definition",
                "canonical_for": "test definition",
                "payload": [],
            },
            self.catalog["traits"],
        )
        self.assertNotIn("contradicted_by", replica["relationships"])
        self.assertNotIn("contradicted_by", definition["relationships"])


class ResolutionStillWorksTests(unittest.TestCase):
    def test_all_shipped_fixtures_resolve(self):
        catalog = load_catalog(CONTRACTS)
        fixtures = sorted(FIXTURE_DIR.glob("*.json"))
        self.assertTrue(fixtures, "expected shipped fixtures")
        for path in fixtures:
            with self.subTest(fixture=path.name):
                resolve_fixture(path, catalog)

    def test_this_repo_design_resolves(self):
        catalog = load_catalog(CONTRACTS)
        design_path = REPO_ROOT / ".artifacts" / "project-design.json"
        design = json.loads(design_path.read_text())
        resolve_project(design, catalog, design_path=design_path)


if __name__ == "__main__":
    unittest.main()
