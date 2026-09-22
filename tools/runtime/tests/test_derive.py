"""Tests for read-time derivation of `ready`/`wave` (derive.py) and its wiring
into query.py (`--where derived.<field>`), contract.py (view role selection),
handoff.py (`requires_payload: ["derived.<field>"]`), and artifacts.py's
list/view/handoff commands.

Part A is pure unit tests against derive.py's graph logic, using plain record
dicts and a minimal single-record-type contract -- no store, no CLI, no git.
Part B drives the real CLI/store against a hand-built resolved contract that
splices a genuine `staged-progress` task-pattern record (composed via
design/contracts/resolve.compose_pattern_record, so its lifecycle/relationships
are the real thing, not a hand-typed guess) plus a view whose role renders
`derived.ready`/`derived.wave` -- something design/contracts/resolve.py's own
selection validator cannot express, so it is added directly to the resolved
contract JSON rather than produced by resolve_project.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import time
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
TOOLS = RUNTIME.parent
REPO_ROOT = TOOLS.parent
CONTRACTS = REPO_ROOT / "design" / "contracts"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(CONTRACTS))

from contract import (  # noqa: E402
    ContractError,
    DERIVED_FIELDS,
    _validate_role_selection,
    record_matches_selection,
    validate_contract_structure,
)
from derive import (  # noqa: E402
    attach_derived,
    attach_derived_all,
    compute_derived,
    eligible_record_types,
    terminal_success_state,
)
from query import QueryError, parse_where, record_matches, where_matches  # noqa: E402
from resolve import compose_pattern_record, load_catalog  # noqa: E402
from revision import compute_revision  # noqa: E402
from support import make_git_repo, load_json, run_cli  # noqa: E402


# --------------------------------------------------------------------------
# Part A: pure unit tests against derive.py
# --------------------------------------------------------------------------

_CATALOG = load_catalog(CONTRACTS)

_WORK_ITEM_DEF = compose_pattern_record(
    {
        "name": "work-item",
        "namespace": "fixture",
        "pattern": "task",
        "canonical_for": "fixture work item",
        "payload": ["title"],
    },
    _CATALOG["traits"],
)

_CYCLIC_LIFECYCLE_DEF = {
    "id": "fixture:cyclic",
    "base_kind": "task",
    "payload": [],
    "relationships": ["depends_on"],
    "storage_capabilities": [],
    "lifecycle": {
        "initial": "a",
        "states": ["a", "b"],
        "transitions": {"a": ["b"], "b": ["a"]},
    },
}

_NO_DEPENDS_DEF = {
    "id": "fixture:plain",
    "base_kind": "task",
    "payload": [],
    "relationships": [],
    "storage_capabilities": [],
    "lifecycle": {"initial": "open", "states": ["open", "closed"], "transitions": {"open": ["closed"]}},
}


def _contract(*record_defs: dict) -> dict:
    return {"records": list(record_defs)}


def _item(record_id: str, state: str = "planned", deps: list[str] | None = None, record_type: str = "fixture:work-item") -> dict:
    record = {
        "id": record_id,
        "record_type": record_type,
        "lifecycle_state": state,
        "relationships": {},
    }
    if deps:
        record["relationships"]["depends_on"] = list(deps)
    return record


class TerminalSuccessStateTests(unittest.TestCase):
    def test_staged_progress_yields_done_without_hardcoding(self):
        # The lifecycle is the real, resolved staged-progress lifecycle -- this
        # asserts the *derivation* lands on "done", not that "done" is special-cased.
        self.assertEqual(terminal_success_state(_WORK_ITEM_DEF), "done")

    def test_purely_cyclic_lifecycle_has_no_terminal_success_state(self):
        self.assertIsNone(terminal_success_state(_CYCLIC_LIFECYCLE_DEF))


class EligibleRecordTypesTests(unittest.TestCase):
    def test_only_depends_on_bearing_types_are_eligible(self):
        contract = _contract(_WORK_ITEM_DEF, _NO_DEPENDS_DEF)
        self.assertEqual(eligible_record_types(contract), {"fixture:work-item"})

    def test_no_eligible_types_when_none_declare_depends_on(self):
        contract = _contract(_NO_DEPENDS_DEF)
        self.assertEqual(eligible_record_types(contract), set())


class NoDependenciesTests(unittest.TestCase):
    def test_no_dependencies_is_ready_and_wave_one(self):
        contract = _contract(_WORK_ITEM_DEF)
        records = [_item("fixture:a")]
        derived = compute_derived(records, contract)
        self.assertEqual(derived["fixture:a"], {"ready": True, "wave": 1})

    def test_ready_of_a_no_deps_record_ignores_its_own_state(self):
        # readiness describes "my dependencies are all done", not "I am done".
        contract = _contract(_WORK_ITEM_DEF)
        records = [_item("fixture:a", state="planned")]
        derived = compute_derived(records, contract)
        self.assertTrue(derived["fixture:a"]["ready"])


class ChainTests(unittest.TestCase):
    def test_chain_of_three_waves(self):
        contract = _contract(_WORK_ITEM_DEF)
        records = [
            _item("fixture:a", state="done"),
            _item("fixture:b", state="done", deps=["fixture:a"]),
            _item("fixture:c", deps=["fixture:b"]),
        ]
        derived = compute_derived(records, contract)
        self.assertEqual(derived["fixture:a"]["wave"], 1)
        self.assertEqual(derived["fixture:b"]["wave"], 2)
        self.assertEqual(derived["fixture:c"]["wave"], 3)

    def test_chain_readiness_propagates_from_immediate_dependency_only(self):
        contract = _contract(_WORK_ITEM_DEF)
        records = [
            _item("fixture:a", state="planned"),
            _item("fixture:b", state="done", deps=["fixture:a"]),
            _item("fixture:c", deps=["fixture:b"]),
        ]
        derived = compute_derived(records, contract)
        self.assertFalse(derived["fixture:b"]["ready"])  # a is not done
        # c's only dependency (b) is "done", so c is ready even though the
        # chain's root (a) is not -- readiness is a one-hop check, not transitive.
        self.assertTrue(derived["fixture:c"]["ready"])


class DiamondTests(unittest.TestCase):
    def test_join_is_one_deeper_than_deepest_arm(self):
        contract = _contract(_WORK_ITEM_DEF)
        records = [
            _item("fixture:a"),
            _item("fixture:b", deps=["fixture:a"]),
            _item("fixture:c", deps=["fixture:a"]),
            _item("fixture:d", deps=["fixture:b", "fixture:c"]),
        ]
        derived = compute_derived(records, contract)
        self.assertEqual(derived["fixture:a"]["wave"], 1)
        self.assertEqual(derived["fixture:b"]["wave"], 2)
        self.assertEqual(derived["fixture:c"]["wave"], 2)
        self.assertEqual(derived["fixture:d"]["wave"], 3)

    def test_join_readiness_requires_all_arms_done(self):
        contract = _contract(_WORK_ITEM_DEF)
        records = [
            _item("fixture:a", state="done"),
            _item("fixture:b", state="done", deps=["fixture:a"]),
            _item("fixture:c", state="planned", deps=["fixture:a"]),  # not done
            _item("fixture:d", deps=["fixture:b", "fixture:c"]),
        ]
        derived = compute_derived(records, contract)
        self.assertFalse(derived["fixture:d"]["ready"])


class ReadinessStateTests(unittest.TestCase):
    def test_dependency_not_yet_done_is_not_ready(self):
        contract = _contract(_WORK_ITEM_DEF)
        records = [
            _item("fixture:a", state="in_progress"),
            _item("fixture:b", deps=["fixture:a"]),
        ]
        derived = compute_derived(records, contract)
        self.assertFalse(derived["fixture:b"]["ready"])

    def test_dependency_done_is_ready(self):
        contract = _contract(_WORK_ITEM_DEF)
        records = [
            _item("fixture:a", state="done"),
            _item("fixture:b", deps=["fixture:a"]),
        ]
        derived = compute_derived(records, contract)
        self.assertTrue(derived["fixture:b"]["ready"])

    def test_dependency_withdrawn_is_not_ready(self):
        # Deliberate: abandonment (withdrawn) must never read as satisfaction.
        # withdrawn's lifecycle_state simply never equals the terminal success
        # state ("done"), so this needs no special-casing in derive.py.
        contract = _contract(_WORK_ITEM_DEF)
        records = [
            _item("fixture:a", state="withdrawn"),
            _item("fixture:b", deps=["fixture:a"]),
        ]
        derived = compute_derived(records, contract)
        self.assertFalse(derived["fixture:b"]["ready"])

    def test_dependency_on_purely_cyclic_lifecycle_type_never_ready(self):
        contract = _contract(_CYCLIC_LIFECYCLE_DEF)
        records = [
            _item("fixture:a", state="a", record_type="fixture:cyclic"),
            _item("fixture:b", state="b", deps=["fixture:a"], record_type="fixture:cyclic"),
        ]
        derived = compute_derived(records, contract)
        self.assertFalse(derived["fixture:b"]["ready"])


class CycleTests(unittest.TestCase):
    def test_two_node_cycle_reported_as_none_not_hung(self):
        contract = _contract(_WORK_ITEM_DEF)
        records = [
            _item("fixture:a", deps=["fixture:b"]),
            _item("fixture:b", deps=["fixture:a"]),
        ]
        derived = compute_derived(records, contract)
        self.assertIsNone(derived["fixture:a"]["wave"])
        self.assertIsNone(derived["fixture:b"]["wave"])

    def test_self_loop_is_a_cycle(self):
        contract = _contract(_WORK_ITEM_DEF)
        records = [_item("fixture:a", deps=["fixture:a"])]
        derived = compute_derived(records, contract)
        self.assertIsNone(derived["fixture:a"]["wave"])

    def test_cycle_does_not_poison_an_unrelated_component(self):
        contract = _contract(_WORK_ITEM_DEF)
        records = [
            _item("fixture:a", deps=["fixture:b"]),
            _item("fixture:b", deps=["fixture:a"]),
            _item("fixture:c"),
        ]
        derived = compute_derived(records, contract)
        self.assertEqual(derived["fixture:c"]["wave"], 1)

    def test_cycle_propagates_forward_to_a_downstream_dependent(self):
        contract = _contract(_WORK_ITEM_DEF)
        records = [
            _item("fixture:a", deps=["fixture:b"]),
            _item("fixture:b", deps=["fixture:a"]),
            _item("fixture:d", deps=["fixture:a"]),
        ]
        derived = compute_derived(records, contract)
        self.assertIsNone(derived["fixture:d"]["wave"])


class DanglingDependencyTests(unittest.TestCase):
    def test_dangling_dependency_is_not_ready(self):
        contract = _contract(_WORK_ITEM_DEF)
        records = [_item("fixture:a", deps=["fixture:does-not-exist"])]
        derived = compute_derived(records, contract)
        self.assertFalse(derived["fixture:a"]["ready"])

    def test_dangling_only_dependency_is_skipped_for_wave(self):
        # As if the reference did not exist: wave falls back to 1, not None.
        contract = _contract(_WORK_ITEM_DEF)
        records = [_item("fixture:a", deps=["fixture:does-not-exist"])]
        derived = compute_derived(records, contract)
        self.assertEqual(derived["fixture:a"]["wave"], 1)

    def test_dangling_dependency_alongside_a_real_one_does_not_break_wave(self):
        contract = _contract(_WORK_ITEM_DEF)
        records = [
            _item("fixture:a"),
            _item("fixture:b", deps=["fixture:a", "fixture:does-not-exist"]),
        ]
        derived = compute_derived(records, contract)
        self.assertEqual(derived["fixture:b"]["wave"], 2)


class ComputeDerivedScopeTests(unittest.TestCase):
    def test_empty_when_no_eligible_types(self):
        contract = _contract(_NO_DEPENDS_DEF)
        records = [{"id": "x", "record_type": "fixture:plain", "lifecycle_state": "open", "relationships": {}}]
        self.assertEqual(compute_derived(records, contract), {})

    def test_only_eligible_type_records_get_derived_entries(self):
        contract = _contract(_WORK_ITEM_DEF, _NO_DEPENDS_DEF)
        records = [
            _item("fixture:a"),
            {"id": "fixture:y", "record_type": "fixture:plain", "lifecycle_state": "open", "relationships": {}},
        ]
        derived = compute_derived(records, contract)
        self.assertIn("fixture:a", derived)
        self.assertNotIn("fixture:y", derived)


class AttachDerivedTests(unittest.TestCase):
    def test_attach_derived_adds_field_without_mutating_original(self):
        record = _item("fixture:a")
        derived_map = {"fixture:a": {"ready": True, "wave": 1}}
        out = attach_derived(record, derived_map)
        self.assertEqual(out["derived"], {"ready": True, "wave": 1})
        self.assertNotIn("derived", record)

    def test_attach_derived_returns_same_object_when_absent_from_map(self):
        record = _item("fixture:a")
        out = attach_derived(record, {})
        self.assertIs(out, record)

    def test_attach_derived_all_short_circuits_on_empty_map(self):
        records = [_item("fixture:a"), _item("fixture:b")]
        out = attach_derived_all(records, {})
        self.assertIs(out, records)


class RevisionSafetyTests(unittest.TestCase):
    def test_derived_field_would_change_revision_if_it_ever_leaked_in(self):
        """Demonstrates *why* attach_derived's output must never reach
        compute_revision/write_record: compute_revision hashes every key
        except `revision`, so a leaked `derived` key silently changes the
        persisted hash. This is the hazard the read-time-only layering avoids.
        """
        record = {
            "id": "fixture:a",
            "record_type": "fixture:work-item",
            "subject": "s",
            "payload": {},
            "lifecycle_state": "planned",
            "relationships": {},
        }
        before = compute_revision(record)
        with_derived = attach_derived(record, {"fixture:a": {"ready": True, "wave": 1}})
        after = compute_revision(with_derived)
        self.assertNotEqual(before, after)
        # And the original, unattached record still hashes the same.
        self.assertEqual(compute_revision(record), before)


class PerformanceTests(unittest.TestCase):
    def test_deep_chain_is_linear_not_quadratic_or_recursive(self):
        contract = _contract(_WORK_ITEM_DEF)
        n = 4000
        records = [_item("fixture:0")]
        for i in range(1, n):
            records.append(_item(f"fixture:{i}", deps=[f"fixture:{i - 1}"]))
        start = time.monotonic()
        derived = compute_derived(records, contract)
        elapsed = time.monotonic() - start
        self.assertEqual(derived[f"fixture:{n - 1}"]["wave"], n)
        self.assertLess(elapsed, 5.0)


# --------------------------------------------------------------------------
# query.py: --where derived.<field>
# --------------------------------------------------------------------------


class QueryDerivedNamespaceTests(unittest.TestCase):
    def test_parse_where_accepts_derived_namespace(self):
        self.assertEqual(parse_where(["derived.ready=true"]), [("derived", "ready", True)])

    def test_parse_where_accepts_payload_namespace_unchanged(self):
        self.assertEqual(parse_where(["payload.goal=ship it"]), [("payload", "goal", "ship it")])

    def test_parse_where_rejects_unknown_namespace(self):
        with self.assertRaises(QueryError):
            parse_where(["lifecycle_state=done"])

    def test_where_matches_derived_field(self):
        record = {"derived": {"ready": True, "wave": 2}}
        self.assertTrue(where_matches(record, [("derived", "ready", True)]))
        self.assertFalse(where_matches(record, [("derived", "wave", 3)]))

    def test_record_matches_uses_where_filters_kwarg(self):
        record = {"derived": {"ready": True}, "payload": {}, "subject": "s"}
        self.assertTrue(record_matches(record, where_filters=[("derived", "ready", True)]))


# --------------------------------------------------------------------------
# contract.py: derived.<field> in view role selection
# --------------------------------------------------------------------------

_BARE_OCCUPANT = {"lifecycle": {"states": []}, "payload": []}


class ContractDerivedSelectionTests(unittest.TestCase):
    def test_validate_role_selection_accepts_known_derived_field(self):
        role = {"name": "r", "selection": {"all": [{"field": "derived.ready", "equals": True}]}}
        _validate_role_selection(role, _BARE_OCCUPANT)  # must not raise

    def test_validate_role_selection_rejects_unknown_derived_field(self):
        role = {"name": "r", "selection": {"all": [{"field": "derived.bogus", "equals": 1}]}}
        with self.assertRaises(ContractError):
            _validate_role_selection(role, _BARE_OCCUPANT)

    def test_derived_fields_constant_matches_derive_output_shape(self):
        self.assertEqual(DERIVED_FIELDS, {"ready", "wave"})

    def test_record_matches_selection_true_and_false_on_derived_field(self):
        selection = {"all": [{"field": "derived.ready", "equals": True}]}
        self.assertTrue(record_matches_selection({"derived": {"ready": True}}, selection))
        self.assertFalse(record_matches_selection({"derived": {"ready": False}}, selection))

    def test_record_matches_selection_missing_derived_mapping_is_false(self):
        selection = {"all": [{"field": "derived.ready", "equals": True}]}
        self.assertFalse(record_matches_selection({}, selection))


# --------------------------------------------------------------------------
# Part B: CLI/store integration against a hand-built resolved contract
# --------------------------------------------------------------------------


def _build_fixture_contract() -> dict:
    base = json.loads((REPO_ROOT / ".artifacts" / "resolved-contract.json").read_text())
    contract = copy.deepcopy(base)
    contract["records"].append(copy.deepcopy(_WORK_ITEM_DEF))
    contract["views"].append(
        {
            "id": "fixture:board",
            "name": "board",
            "roles": [
                {
                    "name": "item",
                    "occupant": "fixture:work-item",
                    "selection": {"all": []},
                    "requires_payload": ["title", "derived.ready", "derived.wave"],
                }
            ],
        }
    )
    validate_contract_structure(contract)  # fail fast if the fixture itself is bad
    return contract


class _FixtureStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        self.contract_path = self.repo / "fixture-contract.json"
        self.contract_path.write_text(json.dumps(_build_fixture_contract()))
        self.store = self.repo / ".fixture-store"
        r = run_cli("init", store=self.store, contract=self.contract_path)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def _create(self, subject: str, *, title: str, rels: list[str] | None = None) -> dict:
        args = [
            "create",
            "--type",
            "fixture:work-item",
            "--subject",
            subject,
            "--payload",
            json.dumps({"title": title}),
        ]
        for rel in rels or []:
            args.extend(["--rel", rel])
        r = run_cli(*args, store=self.store)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return load_json(r.stdout)["record"]

    def _transition(self, record: dict, dest: str) -> dict:
        r = run_cli(
            "update",
            "--type",
            record["record_type"],
            "--id",
            record["id"],
            "--transition",
            dest,
            "--expected-revision",
            record["revision"],
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return load_json(r.stdout)["record"]

    def _finish(self, record: dict) -> dict:
        record = self._transition(record, "in_progress")
        return self._transition(record, "done")

    def _list(self, *args: str) -> dict:
        r = run_cli("list", *args, store=self.store)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return load_json(r.stdout)


class CliListDerivedTests(_FixtureStoreTestCase):
    def test_where_derived_ready_and_wave(self):
        root = self._create("root", title="root task")
        root = self._finish(root)
        mid = self._create("mid", title="mid task", rels=[f"depends_on:{root['id']}"])
        leaf_not_done = self._create("leaf", title="not done yet")
        blocked = self._create(
            "blocked", title="blocked task", rels=[f"depends_on:{leaf_not_done['id']}"]
        )

        by_ready_true = self._list("--type", "fixture:work-item", "--where", "derived.ready=true", "--full")
        ids_ready = {r["id"] for r in by_ready_true["records"]}
        self.assertIn(root["id"], ids_ready)
        self.assertIn(mid["id"], ids_ready)
        self.assertIn(leaf_not_done["id"], ids_ready)  # no deps of its own -> ready
        self.assertNotIn(blocked["id"], ids_ready)

        by_wave_two = self._list("--type", "fixture:work-item", "--where", "derived.wave=2", "--full")
        ids_wave_two = {r["id"] for r in by_wave_two["records"]}
        self.assertEqual(ids_wave_two, {mid["id"], blocked["id"]})

    def test_list_summary_surfaces_derived(self):
        root = self._create("root", title="root task")
        out = self._list("--type", "fixture:work-item", "--subject", "root")
        self.assertEqual(out["records"][0]["derived"], {"ready": True, "wave": 1})


class CliViewDerivedTests(_FixtureStoreTestCase):
    def test_view_role_renders_derived_ready_and_wave(self):
        root = self._create("root", title="root task")
        root = self._finish(root)
        self._create("mid", title="mid task", rels=[f"depends_on:{root['id']}"])
        r = run_cli("view", "--id", "fixture:board", store=self.store)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("root task", r.stdout)
        self.assertIn("mid task", r.stdout)
        self.assertIn("True", r.stdout)
        self.assertIn("2", r.stdout)


class CliRoundTripTests(_FixtureStoreTestCase):
    def test_derived_absent_from_disk_and_revision_after_being_read_with_derivation(self):
        root = self._create("root", title="root task")
        mid = self._create("mid", title="mid task", rels=[f"depends_on:{root['id']}"])

        # Force derivation to run (list attaches `derived` to in-memory copies).
        listed = self._list("--type", "fixture:work-item", "--full")
        self.assertTrue(any("derived" in r for r in listed["records"]))

        # The store itself must be untouched: a fresh raw read shows no
        # `derived` key and an unchanged revision.
        r = run_cli("get", "--type", "fixture:work-item", "--id", mid["id"], store=self.store)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        on_disk = load_json(r.stdout)
        self.assertNotIn("derived", on_disk)
        self.assertEqual(on_disk["revision"], mid["revision"])

        raw_text = (
            self.store / "records" / "fixture__work-item" / f"{mid['id']}.md"
        ).read_text()
        self.assertNotIn("derived", raw_text)


class CliCycleTests(_FixtureStoreTestCase):
    def test_cycle_can_be_written_but_reads_as_none_not_an_error(self):
        x = self._create("x", title="x task")
        y = self._create("y", title="y task", rels=[f"depends_on:{x['id']}"])
        # Close the cycle by pointing x back at y via update, riding along with
        # a legal transition -- validate_relationships only checks that targets
        # exist, so writing a cycle into the store is allowed; only the
        # read-time wave computation needs to detect and report it.
        r = run_cli(
            "update",
            "--type",
            "fixture:work-item",
            "--id",
            x["id"],
            "--transition",
            "in_progress",
            "--expected-revision",
            x["revision"],
            "--rel",
            f"depends_on:{y['id']}",
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

        out = self._list("--type", "fixture:work-item", "--full")
        by_id = {r["id"]: r for r in out["records"]}
        self.assertIsNone(by_id[x["id"]]["derived"]["wave"])
        self.assertIsNone(by_id[y["id"]]["derived"]["wave"])


class ContractWithNothingDerivedTests(unittest.TestCase):
    """A contract that declares no depends_on-bearing record type must behave
    exactly as before this feature existed: no `derived` key anywhere."""

    def setUp(self):
        self.repo = make_git_repo()
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        self.store = self.repo / ".plain-store"
        from support import RESOLVED, sample_finding_payload

        r = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        r = run_cli(
            "create",
            "--type",
            "project:finding",
            "--subject",
            "a finding",
            "--payload",
            json.dumps(sample_finding_payload()),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def test_list_full_has_no_derived_key(self):
        r = run_cli("list", "--type", "project:finding", "--full", store=self.store)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = load_json(r.stdout)
        for record in out["records"]:
            self.assertNotIn("derived", record)

    def test_list_summary_has_no_derived_key(self):
        r = run_cli("list", "--type", "project:finding", store=self.store)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = load_json(r.stdout)
        for record in out["records"]:
            self.assertNotIn("derived", record)


if __name__ == "__main__":
    unittest.main()
