"""Load and query a frozen resolved project contract."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

class ContractError(Exception):
    pass


EXPECTED_CONTRACT_FORMAT = "adaptive-artifacts/resolved-contract@0.3.0"

# Kept in sync with derive.compute_derived's output shape. Defined here (the
# schema-validation module) rather than in derive.py to avoid derive.py <->
# contract.py becoming a cycle; derive.py doesn't need to import this.
DERIVED_FIELDS = frozenset({"ready", "wave", "referenced_by", "corrected"})

# equals alone cannot express "open work" once status lives in the lifecycle:
# there is no single state meaning not-finished.
SELECTION_OPERATORS = frozenset({"equals", "not_equals", "any_of", "within"})
WINDOW_PATTERN = re.compile(r"([1-9][0-9]*)([mhd])")
WINDOW_UNITS = {"m": "minutes", "h": "hours", "d": "days"}
EXPECTED_BACKEND_GUARANTEES = {
    "writer_model": "single_writer",
    "record_write": "atomic_replace",
    "conflict_detection": "revision_token",
    "multi_record_write": "non_transactional",
    "durability": "working_tree",
}


def canonical_digest(data: Any) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def contract_digest(contract: dict[str, Any]) -> str:
    return canonical_digest(contract)


def parse_window(value: Any) -> timedelta | None:
    match = WINDOW_PATTERN.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None
    return timedelta(**{WINDOW_UNITS[match.group(2)]: int(match.group(1))})


def _validate_role_selection(role: dict[str, Any], occupant: dict[str, Any]) -> None:
    selection = role.get("selection")
    if not isinstance(selection, dict) or set(selection) != {"all"}:
        raise ContractError(f"{role.get('name')}: invalid selection")
    clauses = selection["all"]
    if not isinstance(clauses, list):
        raise ContractError(f"{role.get('name')}: selection.all must be a list")
    for clause in clauses:
        if not isinstance(clause, dict) or "field" not in clause:
            raise ContractError(f"{role.get('name')}: invalid selection clause")
        operators = set(clause) - {"field"}
        if len(operators) != 1 or not operators <= SELECTION_OPERATORS:
            raise ContractError(
                f"{role.get('name')}: selection clause needs exactly one of "
                f"{sorted(SELECTION_OPERATORS)}"
            )
        operator = operators.pop()
        expected = clause[operator]
        if operator == "any_of" and not isinstance(expected, list):
            raise ContractError(f"{role.get('name')}: any_of takes a list")
        field = clause["field"]
        if (field == "recorded_at") != (operator == "within"):
            raise ContractError(
                f"{role.get('name')}: within applies only to recorded_at, and recorded_at only to within"
            )
        if field == "recorded_at":
            if parse_window(expected) is None:
                raise ContractError(
                    f"{role.get('name')}: within takes a window like '24h', '7d', '30m'"
                )
        elif field == "lifecycle_state":
            wanted = expected if operator == "any_of" else [expected]
            unknown = [value for value in wanted if value not in occupant["lifecycle"]["states"]]
            if unknown:
                raise ContractError(
                    f"{role.get('name')}: selection uses invalid lifecycle state {unknown}"
                )
        elif isinstance(field, str) and field.startswith("payload."):
            payload_field = field[len("payload.") :]
            if payload_field not in occupant["payload"]:
                raise ContractError(
                    f"{role.get('name')}: selection uses absent payload field"
                )
        elif isinstance(field, str) and field.startswith("derived."):
            derived_field = field[len("derived.") :]
            if derived_field not in DERIVED_FIELDS:
                raise ContractError(
                    f"{role.get('name')}: selection uses unknown derived field {derived_field!r}"
                )
        else:
            raise ContractError(
                f"{role.get('name')}: unsupported selection field {field!r}"
            )


def _validate_view(view: dict[str, Any], defs: dict[str, dict[str, Any]]) -> None:
    view_id = view.get("id")
    if not isinstance(view_id, str) or ":" not in view_id:
        raise ContractError(f"view {view_id!r} requires a qualified id")
    roles = view.get("roles")
    if not isinstance(roles, list):
        raise ContractError(f"{view_id}: roles must be a list")
    parameters = view.get("parameters")
    if parameters is not None and not isinstance(parameters, dict):
        raise ContractError(f"{view_id}: parameters must be an object")
    seen: set[str] = set()
    for role in roles:
        if not isinstance(role, dict):
            raise ContractError(f"{view_id}: roles must be objects")
        name = role.get("name")
        if not isinstance(name, str) or not name:
            raise ContractError(f"{view_id}: role missing name")
        if name in seen:
            raise ContractError(f"{view_id}: duplicate role {name!r}")
        seen.add(name)
        occupant = defs.get(role.get("occupant"))
        if occupant is None:
            raise ContractError(f"{view_id}.{name}: unknown role occupant")
        _validate_role_selection(role, occupant)


def validate_contract_structure(contract: dict[str, Any]) -> None:
    if contract.get("format") != EXPECTED_CONTRACT_FORMAT:
        raise ContractError(
            f"unsupported resolved contract format {contract.get('format')!r}"
        )
    records = contract.get("records")
    views = contract.get("views")
    backend = contract.get("backend")
    if not isinstance(records, list) or not isinstance(views, list):
        raise ContractError("resolved contract requires record and view lists")
    if not isinstance(backend, dict) or backend.get("name") != "git-filesystem":
        raise ContractError("runtime requires the git-filesystem backend")
    if backend.get("guarantees") != EXPECTED_BACKEND_GUARANTEES:
        raise ContractError("git-filesystem guarantees do not match runtime semantics")
    capabilities = backend.get("capabilities")
    if not isinstance(capabilities, list):
        raise ContractError("backend capabilities must be a list")

    defs: dict[str, dict[str, Any]] = {}
    required_capabilities = {"stable_ids", "read", "list"}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise ContractError("each record definition requires an id")
        record_id = record["id"]
        if record_id in defs:
            raise ContractError(f"duplicate record definition {record_id!r}")
        if not isinstance(record.get("base_kind"), str):
            raise ContractError(f"{record_id}: base_kind must be a string")
        if not isinstance(record.get("payload"), list):
            raise ContractError(f"{record_id}: payload must be a list")
        optional_payload = record.get("optional_payload")
        if optional_payload is not None and not isinstance(optional_payload, list):
            raise ContractError(f"{record_id}: optional_payload must be a list")
        payload_enum = record.get("payload_enum")
        if payload_enum is not None and not isinstance(payload_enum, dict):
            raise ContractError(f"{record_id}: payload_enum must be an object")
        lifecycle = record.get("lifecycle")
        if not isinstance(lifecycle, dict) or not isinstance(
            lifecycle.get("states"), list
        ):
            raise ContractError(f"{record_id}: invalid lifecycle")
        if lifecycle.get("initial") not in lifecycle["states"]:
            raise ContractError(f"{record_id}: invalid initial lifecycle state")
        if not isinstance(record.get("relationships"), list):
            raise ContractError(f"{record_id}: relationships must be a list")
        storage = record.get("storage_capabilities")
        if not isinstance(storage, list):
            raise ContractError(f"{record_id}: storage_capabilities must be a list")
        required_capabilities.update(storage)
        defs[record_id] = record
    missing_capabilities = required_capabilities - set(capabilities)
    if missing_capabilities:
        raise ContractError(
            f"backend missing required capabilities {sorted(missing_capabilities)}"
        )

    seen_views: set[str] = set()
    for view in views:
        if not isinstance(view, dict):
            raise ContractError("views must be objects")
        view_id = view.get("id")
        if view_id in seen_views:
            raise ContractError(f"duplicate view {view_id!r}")
        seen_views.add(view_id)
        _validate_view(view, defs)

    bundles = contract.get("bundles") or []
    if not isinstance(bundles, list):
        raise ContractError("bundles must be a list")
    for bundle in bundles:
        if not isinstance(bundle, dict) or not isinstance(bundle.get("id"), str):
            raise ContractError("each bundle requires an id")
        record_ids = bundle.get("records")
        if not isinstance(record_ids, list):
            raise ContractError(f"{bundle['id']}: records must be a list")
        for record_id in record_ids:
            if record_id not in defs:
                raise ContractError(f"{bundle['id']}: unknown record {record_id!r}")
        for link in bundle.get("relationships") or []:
            if not isinstance(link, dict):
                raise ContractError(f"{bundle['id']}: relationships must be objects")
            if link.get("from") not in defs or link.get("to") not in defs:
                raise ContractError(f"{bundle['id']}: relationship endpoints unknown")


def load_contract(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ContractError(f"missing resolved contract: {path}")
    with path.open() as handle:
        contract = json.load(handle)
    if not isinstance(contract, dict):
        raise ContractError("resolved contract must be a JSON object")
    validate_contract_structure(contract)
    return contract


def record_defs(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {record["id"]: record for record in contract["records"]}


def view_by_id(contract: dict[str, Any], view_id: str) -> dict[str, Any]:
    for view in contract.get("views") or []:
        if view.get("id") == view_id:
            return view
    raise ContractError(f"view {view_id!r} not found in contract")


def bundle_by_id(contract: dict[str, Any], bundle_id: str) -> dict[str, Any]:
    for bundle in contract.get("bundles") or []:
        if bundle.get("id") == bundle_id:
            return bundle
    raise ContractError(f"bundle {bundle_id!r} not found in contract")


def handoff_view(contract: dict[str, Any]) -> dict[str, Any]:
    for view in contract.get("views") or []:
        if view.get("name") == "handoff":
            return view
    raise ContractError("handoff view not found in contract")


def role_occupants(view: dict[str, Any]) -> dict[str, str]:
    return {role["name"]: role["occupant"] for role in view["roles"]}


def record_matches_selection(
    record: dict[str, Any],
    selection: dict[str, Any],
    now: datetime | None = None,
) -> bool:
    clauses = selection.get("all")
    if not isinstance(clauses, list):
        raise ContractError("view role selection must contain an 'all' list")
    for clause in clauses:
        field = clause.get("field")
        operators = set(clause) - {"field"}
        if len(operators) != 1 or not operators <= SELECTION_OPERATORS:
            raise ContractError("invalid view role selection clause")
        operator = operators.pop()
        if field == "recorded_at" and operator == "within":
            window = parse_window(clause[operator])
            if window is None:
                raise ContractError(f"invalid recorded_at window {clause[operator]!r}")
            recorded_at = record.get("recorded_at")
            if not recorded_at:
                return False
            current = now or datetime.now(timezone.utc)
            if datetime.fromisoformat(recorded_at) < current - window:
                return False
            continue
        if field == "lifecycle_state":
            actual = record.get("lifecycle_state")
        elif isinstance(field, str) and field.startswith("payload."):
            actual = record.get("payload", {}).get(field[len("payload.") :])
        elif isinstance(field, str) and field.startswith("derived."):
            actual = (record.get("derived") or {}).get(field[len("derived.") :])
        else:
            raise ContractError(f"unsupported view role selection field {field!r}")
        expected = clause[operator]
        if operator == "equals" and actual != expected:
            return False
        if operator == "not_equals" and actual == expected:
            return False
        if operator == "any_of" and actual not in expected:
            return False
    return True


def allowed_transition(record_def: dict[str, Any], src: str, dest: str) -> bool:
    lifecycle = record_def["lifecycle"]
    if dest not in lifecycle["states"]:
        return False
    return dest in lifecycle.get("transitions", {}).get(src, [])


def initial_state(record_def: dict[str, Any]) -> str:
    return record_def["lifecycle"]["initial"]


def storage_capabilities(record_def: dict[str, Any]) -> set[str]:
    return set(record_def.get("storage_capabilities") or [])


def requires_history(record_def: dict[str, Any]) -> bool:
    return "history" in storage_capabilities(record_def)


def is_append_only(record_def: dict[str, Any]) -> bool:
    caps = storage_capabilities(record_def)
    return "append_with_audit" in caps and "conditional_mutation" not in caps


def advertises_supersedes(record_def: dict[str, Any]) -> bool:
    return "supersedes" in record_def.get("relationships", [])


def advertises_corrects(record_def: dict[str, Any]) -> bool:
    return "corrects" in record_def.get("relationships", [])


def has_trait(record_def: dict[str, Any], trait: str) -> bool:
    return trait in (record_def.get("traits") or [])


def requires_dimension(record_def: dict[str, Any], dimension: str) -> bool:
    return dimension in (record_def.get("required_dimensions") or [])
