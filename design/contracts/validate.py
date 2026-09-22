#!/usr/bin/env python3
"""Validate trait composition, resolution, and the three project fixtures."""

from __future__ import annotations

import copy
import json
import sys

from resolve import (
    FIXTURE_DIR,
    RESOLVED_DIR,
    ResolveError,
    compose_record,
    design_digest,
    dump_contract,
    format_id,
    load_catalog,
    load_json,
    resolve_bundles,
    resolve_project,
    validate_selection,
    write_contract,
    build_source_lock,
    compose_pattern_record,
)


def fail(errors: list[str], msg: str) -> None:
    errors.append(msg)


def role_map(contract: dict) -> dict[tuple[str, str], dict]:
    return {
        (view["id"], role["name"]): role
        for view in contract["views"]
        for role in view["roles"]
    }


def check_future_gap(gap: dict, contract: dict, errors: list[str]) -> None:
    occupancy = gap.get("would_occupy")
    if not occupancy:
        return
    view_key = occupancy["view"]
    if ":" not in view_key:
        view_key = f"project:{view_key}"
    role = role_map(contract).get((view_key, occupancy["role"]))
    if role is None:
        fail(
            errors,
            f"{contract['project']}: gap {gap.get('future_type')} occupies unknown {occupancy}",
        )
        return
    provided = set(gap.get("must_provide_traits", []))
    missing = set(role["requires"]) - provided
    if missing:
        fail(
            errors,
            f"{contract['project']}: {gap.get('future_type')} missing role traits {sorted(missing)}",
        )
    required_kind = role.get("base_kind")
    if required_kind and gap.get("base_kind") not in (None, required_kind):
        fail(
            errors,
            f"{contract['project']}: {gap.get('future_type')} base_kind "
            f"{gap.get('base_kind')} != {required_kind}",
        )


def check_contract(
    design: dict, contract: dict, catalog: dict, errors: list[str]
) -> None:
    project = contract["project"]
    expected_design_format = format_id(
        "project-design", catalog["meta"]["project_design_format"]
    )
    expected_contract_format = format_id(
        "resolved-contract", catalog["meta"]["resolved_contract_format"]
    )
    if design.get("format") != expected_design_format:
        fail(errors, f"{project}: unexpected project design format")
    if contract.get("format") != expected_contract_format:
        fail(errors, f"{project}: unexpected resolved contract format")
    if "families" in contract:
        fail(errors, f"{project}: resolved contract must not list families")
    if contract["backend"]["match"] != "ok":
        fail(errors, f"{project}: backend mismatch {contract['backend']['missing']}")
    guarantees = contract["backend"].get("guarantees", {})
    if guarantees.get("writer_model") != "single_writer":
        fail(errors, f"{project}: git backend must declare single-writer semantics")
    if guarantees.get("record_write") != "atomic_replace":
        fail(errors, f"{project}: git backend must declare atomic record writes")
    if guarantees.get("conflict_detection") != "revision_token":
        fail(errors, f"{project}: git backend must declare revision conflict detection")
    if guarantees.get("multi_record_write") != "non_transactional":
        fail(errors, f"{project}: git backend must expose non-transactional multi-record writes")
    baseline = contract["backend"].get("baseline_required", [])
    if not all(item in contract["backend"]["required"] for item in baseline):
        fail(errors, f"{project}: backend missing baseline capabilities")
    resolution = contract.get("resolution", {})
    if not resolution:
        fail(errors, f"{project}: missing resolution block")
    lock = resolution.get("source_lock")
    if not lock:
        fail(errors, f"{project}: resolution missing source_lock")
    if resolution.get("design_digest") != design_digest(design):
        fail(errors, f"{project}: design_digest mismatch")
    digests = resolution.get("source_digests", {})
    if digests.get("catalog.json") != lock.get("catalog"):
        fail(errors, f"{project}: catalog digest missing or inconsistent")
    if any(key.startswith("families/") for key in digests):
        fail(errors, f"{project}: resolution includes family digests")

    record_ids = [record["id"] for record in contract["records"]]
    expected_ids = [
        "project:current-position",
        "project:active-commitment",
        "project:continuity-question",
        "project:active-goal",
        "project:next-action",
        "project:investigation-question",
        "project:investigation-observation",
        "project:finding",
        "project:failed-attempt",
    ]
    missing = [item for item in expected_ids if item not in record_ids]
    if missing:
        fail(errors, f"{project}: missing pattern records {missing}")
    if project == "parcelpipe":
        extra = [
            "project:work-item",
            "project:acceptance",
            "project:check-run",
        ]
        absent = [item for item in extra if item not in record_ids]
        if absent:
            fail(errors, f"{project}: missing pattern records {absent}")
        work = next((r for r in contract["records"] if r["id"] == "project:work-item"), None)
        if work:
            if work.get("pattern") != "current-status":
                fail(errors, f"{project}: work-item pattern {work.get('pattern')}")
            if "current-claim" not in work.get("traits", []):
                fail(errors, f"{project}: work-item must derive current-claim")
        check = next((r for r in contract["records"] if r["id"] == "project:check-run"), None)
        if check and check.get("pattern") != "event":
            fail(errors, f"{project}: check-run pattern {check.get('pattern')}")
        if check and "occurrence" not in check.get("traits", []):
            fail(errors, f"{project}: check-run must derive occurrence")

    failed = next(r for r in contract["records"] if r["name"] == "failed-attempt")
    if "observation" in failed["payload"] or "conclusion" in failed["payload"]:
        fail(errors, f"{project}: failed-attempt must be atomic by payload")
    if "informed_by" not in failed.get("relationships", []):
        fail(errors, f"{project}: failed-attempt must advertise informed_by from traits")
    if failed["lifecycle"]["states"] != ["recorded"]:
        fail(errors, f"{project}: failed-attempt lifecycle must stay recorded")
    if failed.get("pattern") != "event":
        fail(errors, f"{project}: failed-attempt must be an event pattern")

    observation = next(r for r in contract["records"] if r["name"] == "investigation-observation")
    if observation.get("pattern") != "observation":
        fail(errors, f"{project}: investigation-observation must use observation pattern")
    if observation.get("base_kind") != "observation":
        fail(errors, f"{project}: investigation-observation base_kind")

    abandoned = next(b for b in contract["bundles"] if b["id"] == "project:abandoned-path")
    link = abandoned.get("relationships", [{}])[0]
    if link.get("from") != "project:failed-attempt":
        fail(errors, f"{project}: failed-attempt must be relationship source")
    if link.get("to") != "project:investigation-observation":
        fail(errors, f"{project}: investigation-observation must be relationship target")
    if link.get("type") != "informed_by":
        fail(errors, f"{project}: abandoned-path link must be informed_by")

    expected_bundles = {
        "project:session-continuity",
        "project:abandoned-path",
        "project:concluded-investigation",
    }
    if {bundle["id"] for bundle in contract["bundles"]} != expected_bundles:
        fail(errors, f"{project}: bundles {contract['bundles']}")

    questions = {
        record["name"]: record
        for record in contract["records"]
        if record["name"] in {"continuity-question", "investigation-question"}
    }
    left = questions["continuity-question"]
    right = questions["investigation-question"]
    if left["traits"] != right["traits"]:
        fail(errors, f"{project}: question types should share open-question traits")
    if left["payload"] == right["payload"] and left["read_policy"] == right["read_policy"]:
        fail(errors, f"{project}: question types collapsed")

    occupancy = {
        (view["id"], role["name"]): role["occupant"]
        for view in contract["views"]
        for role in view["roles"]
    }
    expected = {
        ("project:handoff", "goal"): "project:active-goal",
        ("project:handoff", "position"): "project:current-position",
        ("project:handoff", "next"): "project:next-action",
        ("project:handoff", "commitment"): "project:active-commitment",
        ("project:handoff", "blocking-question"): "project:continuity-question",
        ("project:investigation-summary", "question"): "project:investigation-question",
        ("project:investigation-summary", "observation"): "project:investigation-observation",
        ("project:investigation-summary", "finding"): "project:finding",
        ("project:investigation-summary", "failed-attempt"): "project:failed-attempt",
    }
    if occupancy != expected:
        fail(errors, f"{project}: occupancy {occupancy} != defaults")

    handoff_question = next(
        role
        for view in contract["views"]
        if view["id"] == "project:handoff"
        for role in view["roles"]
        if role["name"] == "blocking-question"
    )
    if handoff_question["candidates"] != ["project:continuity-question"]:
        fail(
            errors,
            f"{project}: blocking-question candidates must provide blocking payload",
        )
    if handoff_question.get("requires_payload") != ["blocking", "scope"]:
        fail(errors, f"{project}: blocking-question must require blocking and scope payload")
    if handoff_question.get("selection") != {
        "all": [
            {"field": "lifecycle_state", "equals": "open"},
            {"field": "payload.blocking", "equals": True},
        ]
    }:
        fail(errors, f"{project}: blocking-question selection not contractual")

    handoff_roles = {
        role["name"]: role
        for view in contract["views"]
        if view["id"] == "project:handoff"
        for role in view["roles"]
    }
    if handoff_roles["goal"]["candidates"] != ["project:active-goal"]:
        fail(errors, f"{project}: goal candidates must be active-goal only")
    if handoff_roles["goal"].get("requires_payload") != ["goal", "scope"]:
        fail(errors, f"{project}: goal must require goal and scope payload")
    if handoff_roles["next"]["candidates"] != ["project:next-action"]:
        fail(errors, f"{project}: next candidates must be next-action only")
    if handoff_roles["next"].get("requires_payload") != ["next", "scope"]:
        fail(errors, f"{project}: next must require next and scope payload")
    if handoff_roles["position"]["candidates"] != ["project:current-position"]:
        fail(errors, f"{project}: position candidates must not include goal or next")
    if handoff_roles["position"].get("requires_payload") != ["position", "scope"]:
        fail(errors, f"{project}: position must require position and scope payload")

    for gap in design.get("gaps", []):
        check_future_gap(gap, contract, errors)

    executable = {c["name"] for c in design.get("experimental_candidates", [])}
    for gap in design.get("gaps", []):
        if gap.get("future_type") in executable:
            fail(errors, f"{project}: gap duplicates executable candidate {gap['future_type']}")

    for candidate in contract.get("experimental_candidates", []):
        compat = candidate.get("role_compatibility")
        if not compat or not compat.get("compatible"):
            fail(errors, f"{project}: {candidate['id']} missing role_compatibility")
        if candidate.get("occupancy"):
            fail(errors, f"{project}: {candidate['id']} must not use occupancy")


def expect_error(label: str, fn, errors: list[str]) -> None:
    try:
        fn()
    except ResolveError:
        return
    fail(errors, f"{label}: expected ResolveError")


def synthetic_namespace_bundles(catalog: dict, errors: list[str]) -> None:
    traits = catalog["traits"]
    records = {}
    for namespace, trait_spec, extra in (
        ("alpha", ["entity", "epistemic-claim"], {}),
        (
            "beta",
            ["entity", "occurrence"],
            {"base_kind": "observation"},
        ),
    ):
        composed = compose_record(
            {"name": "item", "traits": trait_spec, "payload": [], **extra},
            namespace,
            traits,
        )
        records[composed["id"]] = composed
    try:
        left = resolve_bundles(
            [{"name": "capture-set", "records": ["item"]}],
            {k: v for k, v in records.items() if k.startswith("alpha:")},
            namespace="alpha",
        )
        right = resolve_bundles(
            [{"name": "capture-set", "records": ["item"]}],
            {k: v for k, v in records.items() if k.startswith("beta:")},
            namespace="beta",
        )
    except ResolveError as exc:
        fail(errors, f"synthetic namespace bundles: {exc}")
        return
    ids = {bundle["id"] for bundle in left + right}
    if ids != {"alpha:capture-set", "beta:capture-set"}:
        fail(errors, f"synthetic namespace bundles: unexpected ids {ids}")


def bundle_link_cases(catalog: dict, errors: list[str]) -> None:
    traits = catalog["traits"]
    records = {}
    for spec in (
        {
            "name": "attempt",
            "traits": ["entity", "occurrence", "evidence-linked"],
            "base_kind": "event",
            "payload": [],
        },
        {
            "name": "observation",
            "traits": ["entity", "occurrence"],
            "base_kind": "observation",
            "payload": [],
        },
    ):
        composed = compose_record(spec, "test", traits)
        records[composed["id"]] = composed

    expect_error(
        "unsupported bundle relationship",
        lambda: resolve_bundles(
            [
                {
                    "name": "bad-type",
                    "records": ["attempt", "observation"],
                    "relationships": [
                        {"from": "attempt", "to": "observation", "type": "supports"}
                    ],
                }
            ],
            records,
            namespace="test",
        ),
        errors,
    )

    expect_error(
        "bundle link endpoint outside bundle",
        lambda: resolve_bundles(
            [
                {
                    "name": "bad-endpoint",
                    "records": ["attempt"],
                    "relationships": [
                        {"from": "attempt", "to": "observation", "type": "informed_by"}
                    ],
                }
            ],
            records,
            namespace="test",
        ),
        errors,
    )


def compatibility_cases(catalog: dict, parcelpipe: dict, errors: list[str]) -> None:
    traits = catalog["traits"]
    missing_format = copy.deepcopy(parcelpipe)
    del missing_format["format"]
    expect_error(
        "missing project design format",
        lambda: resolve_project(missing_format, catalog),
        errors,
    )
    expect_error(
        "current-claim + occurrence",
        lambda: compose_record(
            {
                "name": "illegal",
                "traits": ["entity", "current-claim", "occurrence"],
                "payload": [],
            },
            "test",
            traits,
        ),
        errors,
    )
    expect_error(
        "record-owned lifecycle",
        lambda: compose_record(
            {
                "name": "illegal",
                "traits": ["entity", "current-claim"],
                "payload": [],
                "lifecycle": {
                    "initial": "active",
                    "states": ["active", "superseded"],
                    "transitions": {"active": ["superseded"]},
                },
            },
            "test",
            traits,
        ),
        errors,
    )
    expect_error(
        "record-owned relationships",
        lambda: compose_record(
            {
                "name": "illegal",
                "traits": ["entity", "occurrence"],
                "base_kind": "event",
                "payload": [],
                "relationships": ["informed_by"],
            },
            "test",
            traits,
        ),
        errors,
    )
    expect_error(
        "unsupported view selection field",
        lambda: validate_selection(
            {"all": [{"field": "stewardship.owner", "equals": "agent"}]},
            [],
            "test:view.role",
        ),
        errors,
    )
    expect_error(
        "view selection references absent payload",
        lambda: validate_selection(
            {"all": [{"field": "payload.blocking", "equals": True}]},
            [
                compose_record(
                    {
                        "name": "question",
                        "traits": ["entity", "open-question"],
                        "payload": ["owner"],
                    },
                    "test",
                    traits,
                )
            ],
            "test:view.role",
        ),
        errors,
    )

    missing_lock = copy.deepcopy(parcelpipe)
    del missing_lock["source_lock"]
    expect_error(
        "missing source_lock",
        lambda: resolve_project(missing_lock, catalog),
        errors,
    )

    stale_catalog = copy.deepcopy(parcelpipe)
    stale_catalog["source_lock"]["catalog"] = (
        "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    )
    expect_error(
        "stale catalog digest",
        lambda: resolve_project(stale_catalog, catalog),
        errors,
    )

    stale_traits = copy.deepcopy(parcelpipe)
    stale_traits["source_lock"]["traits"] = (
        "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    )
    expect_error(
        "stale traits digest",
        lambda: resolve_project(stale_traits, catalog),
        errors,
    )

    leftover_families = copy.deepcopy(parcelpipe)
    leftover_families["families"] = []
    expect_error(
        "families key rejected",
        lambda: resolve_project(leftover_families, catalog),
        errors,
    )

    leftover_lock = copy.deepcopy(parcelpipe)
    leftover_lock["source_lock"]["families"] = {}
    expect_error(
        "source_lock families key rejected",
        lambda: resolve_project(leftover_lock, catalog),
        errors,
    )

    missing_audit = copy.deepcopy(parcelpipe)
    missing_audit["backend"] = "ephemeral-memory"
    expect_error(
        "ephemeral-memory vs occurrence",
        lambda: resolve_project(missing_audit, catalog),
        errors,
    )

    bad_occupancy = copy.deepcopy(parcelpipe)
    bad_occupancy["occupancy"] = {
        "project:handoff": {"position": "project:finding"}
    }
    expect_error(
        "finding occupying position",
        lambda: resolve_project(bad_occupancy, catalog),
        errors,
    )

    bad_candidate = copy.deepcopy(parcelpipe)
    bad_candidate["experimental_candidates"] = [
        {
            "namespace": "operations",
            "name": "incident",
            "traits": ["entity"],
            "base_kind": "event",
            "payload": ["severity"],
            "role_compatibility": {"view": "project:handoff", "role": "position"},
        }
    ]
    expect_error(
        "incident incompatible with position role",
        lambda: resolve_project(bad_candidate, catalog),
        errors,
    )

    expect_error(
        "unknown pattern",
        lambda: compose_pattern_record(
            {"name": "x", "pattern": "phase", "canonical_for": "x", "payload": []},
            traits,
        ),
        errors,
    )
    expect_error(
        "replica without replica_of",
        lambda: compose_pattern_record(
            {"name": "map", "pattern": "replica", "payload": ["source"]},
            traits,
        ),
        errors,
    )
    dup = copy.deepcopy(parcelpipe)
    dup["records"] = [
        {
            "name": "a",
            "pattern": "current-status",
            "canonical_for": "same claim",
            "payload": ["title"],
        },
        {
            "name": "b",
            "pattern": "definition",
            "canonical_for": "same claim",
            "payload": ["criterion"],
        },
    ]
    expect_error(
        "duplicate canonical_for",
        lambda: resolve_project(dup, catalog),
        errors,
    )

    synthetic_namespace_bundles(catalog, errors)
    bundle_link_cases(catalog, errors)


def main() -> int:
    catalog = load_catalog()
    errors: list[str] = []

    fixtures = [load_json(path) for path in sorted(FIXTURE_DIR.glob("*.json"))]
    actual = {item["project"] for item in fixtures}
    expected = {"parcelpipe", "ml-research", "incident-response"}
    if actual != expected:
        fail(errors, f"expected projects {sorted(expected)}, got {sorted(actual)}")

    locks = [item.get("source_lock") for item in fixtures]
    if len(set(json.dumps(item, sort_keys=True) for item in locks)) != 1:
        fail(errors, "fixtures must share identical source_lock")
    expected_lock = build_source_lock(catalog)
    if locks and locks[0] != expected_lock:
        fail(errors, "fixture source_lock does not match catalog digests")

    contracts = []
    for design in fixtures:
        try:
            contract = resolve_project(design, catalog)
        except ResolveError as exc:
            fail(errors, str(exc))
            continue
        write_contract(contract, RESOLVED_DIR / f"{contract['project']}.json")
        check_contract(design, contract, catalog, errors)
        contracts.append(contract)

    if fixtures:
        compatibility_cases(catalog, fixtures[0], errors)

    ml = next((c for c in contracts if c["project"] == "ml-research"), None)
    if ml:
        ids = {c["id"] for c in ml.get("experimental_candidates", [])}
        if "research:hypothesis" not in ids or "research:experimental-observation" not in ids:
            fail(errors, "ml-research: missing research experimental candidates")
        gap_types = {g.get("future_type") for g in fixtures[1].get("gaps", [])}
        if {"hypothesis", "experimental-observation"} & gap_types:
            fail(errors, "ml-research: executable types must not remain as gaps")

    incident = next((c for c in contracts if c["project"] == "incident-response"), None)
    if incident:
        ids = {c["id"] for c in incident.get("experimental_candidates", [])}
        expected_ops = {
            "operations:incident-position",
            "operations:diagnosis",
            "operations:intervention",
        }
        if not expected_ops <= ids:
            fail(errors, f"incident-response: missing ops candidates {expected_ops - ids}")
        gap_types = {g.get("future_type") for g in fixtures[2].get("gaps", [])}
        if {"incident-position", "diagnosis", "intervention"} & gap_types:
            fail(errors, "incident-response: executable types must not remain as gaps")

    if errors:
        print("contract fixtures: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("contract fixtures: ok")
    print(f"  catalog: {catalog['meta']['version']}")
    print(f"  traits: {', '.join(sorted(catalog['traits']))}")
    print(f"  fixtures: {', '.join(sorted(actual))}")
    print("  resolved:")
    for contract in contracts:
        exp = len(contract.get("experimental_candidates", []))
        print(
            f"    {contract['project']}: {dump_contract(contract).count(chr(10))} lines"
            f" ({exp} experimental candidates)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
