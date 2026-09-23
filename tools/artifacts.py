#!/usr/bin/env python3
"""Contract-driven artifact runtime."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_RUNTIME = Path(__file__).resolve().parent / "runtime"
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))

from _paths import (  # noqa: E402
    contract_path_from_meta,
    contracts_on_path,
    default_store_path,
    project_design_path,
    resolved_contract_path,
)
from contract import (
    ContractError,
    bundle_by_id,
    handoff_view,
    initial_state,
    is_append_only,
    load_contract,
    record_defs,
    record_matches_selection,
    requires_dimension,
    requires_history,
    role_occupants,
    view_by_id,
)
from derive import attach_derived_all, compute_derived
from git_backend import GitContextError, assert_git_context
from handoff import (
    generate_all_views,
    generate_handoff,
    generate_view,
    view_file_name,
    view_is_stale,
)
from query import (
    QueryError,
    compile_grep,
    order_by_recorded_at,
    parse_where,
    record_matches,
    summarize,
)
from store import (
    ContractBindingError,
    PartialStoreError,
    StaleWriteError,
    Store,
    StoreError,
    StoreLockError,
    StoreNotInitializedError,
)
from validation import (
    ValidationError,
    check_transition,
    identity_continues,
    load_records_for_validation,
    position_key,
    reject_append_only_mutation,
    reject_supersede_via_update,
    subject_related,
    validate_record,
    validate_store,
    validate_strict,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_STALE = 2
EXIT_TRANSITION = 3
EXIT_VALIDATION = 4
EXIT_STRICT = 5

# Every command that can write a record or the store itself. Reads (get,
# list, view, handoff, validate, hook-start, hook-stop) and contract tooling
# (resolve, lock) are exempt -- a read-only caller needs the whole store
# visible, just none of it mutable.
MUTATING_COMMANDS = frozenset(
    {"create", "update", "supersede", "correct", "contradict", "capture", "apply", "init"}
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


_UNKNOWN_IDENTITY = "unknown"


def _resolve_identity(args: argparse.Namespace) -> str:
    """--identity, else $ARTIFACTS_IDENTITY, else "unknown".

    "unknown" beats guessing: silently attributing a write to whichever
    session happened to run first is exactly the collision this exists to
    stop being invisible.
    """
    flag = getattr(args, "identity", None)
    if flag:
        return flag
    env = os.environ.get("ARTIFACTS_IDENTITY")
    if env:
        return env
    return _UNKNOWN_IDENTITY


def _is_read_only(args: argparse.Namespace) -> bool:
    """--read-only, else $ADAPTIVE_ARTIFACTS_READONLY=1.

    Checked once in main() before any command dispatch, so a refused command
    never opens the store, reads stdin, or touches the filesystem at all.
    """
    if getattr(args, "read_only", False):
        return True
    return os.environ.get("ADAPTIVE_ARTIFACTS_READONLY") == "1"


def _emit_json(data: Any) -> None:
    print(json.dumps(data, indent=2))


def _load_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise StoreError("payload must be a JSON object")
    return data


class _BodyArgError(Exception):
    pass


def _resolve_body(args: argparse.Namespace) -> tuple[bool, str]:
    """Return (flag_was_given, text). Distinguishes an absent flag from --body ""."""
    body = getattr(args, "body", None)
    body_file = getattr(args, "body_file", None)
    if body is not None and body_file is not None:
        raise _BodyArgError("--body and --body-file are mutually exclusive")
    if body is not None:
        return True, body
    if body_file is not None:
        if body_file == "-":
            return True, sys.stdin.read()
        try:
            return True, Path(body_file).read_text()
        except OSError as exc:
            raise _BodyArgError(f"cannot read --body-file {body_file!r}: {exc}") from exc
    return False, ""


def _store_open_error(exc: Exception) -> tuple[dict[str, Any], int]:
    if isinstance(exc, ContractBindingError):
        return {"error": "contract_drift", "message": str(exc)}, EXIT_VALIDATION
    if isinstance(exc, (StoreNotInitializedError, PartialStoreError)):
        return {"error": "store_not_ready", "message": str(exc)}, EXIT_ERROR
    raise exc


def _handle_store_open_error(exc: Exception) -> int:
    payload, code = _store_open_error(exc)
    _emit_json(payload)
    return code


def _open_store(args: argparse.Namespace) -> tuple[Store, dict[str, Any]]:
    store = Store(Path(args.store))
    contract = _require_contract(args)
    store.require_initialized(contract)
    return store, contract


def _base_record(
    record_type: str,
    record_def: dict[str, Any],
    *,
    subject: str,
    stewardship: dict[str, Any] | str,
    payload: dict[str, Any],
    record_id: str,
    lifecycle_state: str | None = None,
    relationships: dict[str, list[str]] | None = None,
    body: str = "",
    identity: str = _UNKNOWN_IDENTITY,
) -> dict[str, Any]:
    if isinstance(stewardship, str):
        stewardship = {"steward": stewardship}
    record: dict[str, Any] = {
        "id": record_id,
        "record_type": record_type,
        "base_kind": record_def["base_kind"],
        "subject": subject,
        "payload": payload,
        "lifecycle_state": lifecycle_state or initial_state(record_def),
        "relationships": relationships or {},
        "revision": "",
        "body": body,
        "recorded_at": _now(),
        # who (which session) wrote this, distinct from stewardship.steward
        # (what wrote it: agent/human). Top-level and unconditional -- unlike
        # stewardship, not every record type requires that dimension (e.g.
        # project:finding), and identity must not silently vanish for those.
        "identity": identity,
    }
    if requires_dimension(record_def, "stewardship"):
        record["stewardship"] = stewardship
    if requires_dimension(record_def, "epistemic_status"):
        record["epistemic_status"] = "asserted"
    if requires_dimension(record_def, "adoption_or_deontic_status"):
        record["adoption_or_deontic_status"] = "active"
    if requires_dimension(record_def, "time"):
        if record_def["base_kind"] == "claim":
            record["time"] = {"as_of": _now()}
        elif record_def["base_kind"] == "commitment":
            record["time"] = {"effective_time": payload.get("effective_time") or _now()}
        else:
            record["time"] = {
                "observed": payload.get("observed_time") or _now(),
                "recorded": _now(),
            }
    if requires_dimension(record_def, "provenance"):
        sources = []
        for field in ("source", "basis"):
            if payload.get(field):
                sources.append(payload[field])
        if not sources:
            sources = [subject]
        record["provenance"] = {"sources": sources}
    return record


def _supersede_preflight(
    contract: dict[str, Any],
    store: Store,
    old: dict[str, Any],
    new_record: dict[str, Any],
    records: list[dict[str, Any]],
) -> None:
    if not identity_continues(old, new_record):
        raise ValidationError("supersede successor breaks identity continuity")
    if store.record_exists(new_record["record_type"], new_record["id"]):
        raise ValidationError(f"successor id already exists: {new_record['id']}")
    known_ids = {record["id"] for record in records} | {old["id"], new_record["id"]}
    validate_record(contract, new_record, known_ids)
    if old["lifecycle_state"] == "active" and "scope" in (old.get("payload") or {}):
        key = position_key(old)
        for record in records:
            if record["id"] == old["id"]:
                continue
            if record["record_type"] != old["record_type"]:
                continue
            if record["lifecycle_state"] == "active" and position_key(record) == key:
                raise ValidationError(
                    f"another active {old['record_type']} already exists for "
                    f"subject={key[0]!r} scope={key[1]!r}"
                )


_CURRENT_REVISION = "@current"


def _resolve_expected_revision(raw: str | None, old: dict[str, Any]) -> str | None:
    """"@current" trusts the read this call just did, skipping a separate
    `get` -- the exact-revision form remains the real concurrency guard."""
    if raw == _CURRENT_REVISION:
        return old["revision"]
    return raw


def _match_record_types(defs: dict[str, Any], type_arg: str) -> list[str]:
    if type_arg in defs:
        return [type_arg]
    suffix = ":" + type_arg
    return sorted(t for t in defs if t.endswith(suffix))


def _resolve_record_type(
    defs: dict[str, Any], type_arg: str
) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve a qualified or short (unqualified) type name against defs.

    Returns (resolved_type, None) on a unique match, or (None, error_payload)
    for zero or multiple matches -- callers must not silently treat either
    as "no records".
    """
    matches = _match_record_types(defs, type_arg)
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, {"error": "ambiguous_type", "type": type_arg, "candidates": matches}
    return None, {"error": "unknown_type", "type": type_arg}


def _find_record_by_id(
    store: Store, defs: dict[str, Any], record_id: str
) -> dict[str, Any] | None:
    for record_type in defs:
        if store.record_exists(record_type, record_id):
            return store.read_record(record_type, record_id)
    return None


def _parse_rels(raw: list[str] | None) -> dict[str, list[str]]:
    relationships: dict[str, list[str]] = {}
    for item in raw or []:
        if ":" not in item:
            raise StoreError(f"invalid --rel {item!r}; expected type:target_id")
        rel_type, target = item.split(":", 1)
        if not rel_type or not target:
            raise StoreError(f"invalid --rel {item!r}; expected type:target_id")
        relationships.setdefault(rel_type, []).append(target)
    return relationships


def _persist_new(store: Store, record_def: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    stored = store.create_record(record)
    if is_append_only(record_def):
        try:
            store.archive_history(stored)
        except Exception:
            # The caller never learns this id, so it could never roll the file back.
            store.delete_record_file(stored["record_type"], stored["id"])
            raise
    return stored


def _view_store_root(store: Store) -> str:
    """Store root as views should print it: repo-relative when it is inside the cwd."""
    root = store.root.resolve()
    try:
        return root.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return root.as_posix()


def _safe_out_path(store: Store, out: str) -> Path:
    store_root = store.root.resolve()
    out_path = Path(out)
    out_path = out_path.resolve() if out_path.is_absolute() else (store_root / out_path).resolve()
    try:
        out_path.relative_to(store_root)
    except ValueError as exc:
        raise ValidationError("unsafe_output_path") from exc
    return out_path


def _apply_paths(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve() if getattr(args, "root", None) else Path.cwd()
    args.root = root
    if not getattr(args, "store", None):
        args.store = str(default_store_path(root))
    store = Path(args.store)
    if not getattr(args, "contract", None):
        pinned = contract_path_from_meta(store)
        args.contract = str(pinned if pinned is not None else resolved_contract_path(root))


def cmd_lock(args: argparse.Namespace) -> int:
    contracts_on_path()
    from resolve import build_source_lock, load_catalog

    _emit_json(build_source_lock(load_catalog()))
    return EXIT_OK


def cmd_resolve(args: argparse.Namespace) -> int:
    contracts_on_path()
    from resolve import ResolveError, load_catalog, load_json, resolve_project, write_contract

    root = Path(args.root)
    design_path = Path(args.design) if getattr(args, "design", None) else project_design_path(root)
    out_path = Path(args.out) if getattr(args, "out", None) else resolved_contract_path(root)
    if not design_path.is_file():
        _emit_json({"error": "missing_design", "path": str(design_path)})
        return EXIT_ERROR
    try:
        design = load_json(design_path)
        contract = resolve_project(design, load_catalog())
        write_contract(contract, out_path)
        _emit_json({"status": "ok", "path": str(out_path)})
        return EXIT_OK
    except ResolveError as exc:
        _emit_json({"error": "resolve_failed", "message": str(exc)})
        return EXIT_ERROR


def cmd_init(args: argparse.Namespace) -> int:
    try:
        assert_git_context(Path(args.root))
    except GitContextError as exc:
        _emit_json({"error": "git_context", "message": str(exc)})
        return EXIT_ERROR
    contract_path = Path(args.contract)
    if not contract_path.is_file():
        _emit_json({"error": "missing_contract", "path": str(contract_path)})
        return EXIT_ERROR
    contract = load_contract(contract_path)
    store = Store(Path(args.store))
    try:
        with store.write_lock():
            status = store.init(contract, contract_path.resolve())
    except StoreLockError as exc:
        _emit_json({"error": "locked", "message": str(exc)})
        return EXIT_ERROR
    except (PartialStoreError, StoreError) as exc:
        _emit_json({"error": "init_rejected", "message": str(exc)})
        return EXIT_ERROR
    _emit_json({"status": status, "store": str(store.root)})
    return EXIT_OK


def _do_create(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _store_open_error(exc)
    defs = record_defs(contract)
    record_type = args.type
    if record_type not in defs:
        return {"error": "unknown_type", "type": record_type}, EXIT_VALIDATION
    payload = _load_payload(args.payload)
    subject = args.subject or payload.get("subject")
    if not subject:
        return {"error": "missing_subject"}, EXIT_ERROR
    try:
        relationships = _parse_rels(getattr(args, "rel", None))
    except StoreError as exc:
        return {"error": "invalid_rel", "message": str(exc)}, EXIT_ERROR
    try:
        _, body_text = _resolve_body(args)
    except _BodyArgError as exc:
        return {"error": "invalid_body", "message": str(exc)}, EXIT_ERROR
    record_id = store.new_id()
    record = _base_record(
        record_type,
        defs[record_type],
        subject=subject,
        stewardship=args.steward or "agent",
        payload=payload,
        record_id=record_id,
        relationships=relationships or None,
        body=body_text,
        identity=_resolve_identity(args),
    )
    known_ids = {item["id"] for item in store.iter_records()} | {record_id}
    try:
        validate_record(contract, record, known_ids)
    except ValidationError as exc:
        return {"error": "validation", "message": str(exc)}, EXIT_VALIDATION
    stored = _persist_new(store, defs[record_type], record)
    return {"ok": True, "op": "create", "record": stored}, EXIT_OK


def cmd_create(args: argparse.Namespace) -> int:
    payload, code = _do_create(args)
    _emit_json(payload)
    return code


def _do_update(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _store_open_error(exc)
    defs = record_defs(contract)
    try:
        old = store.read_record(args.type, args.id)
    except StoreError as exc:
        return {"error": "not_found", "message": str(exc)}, EXIT_ERROR
    record_def = defs[old["record_type"]]
    src = old["lifecycle_state"]
    transition = getattr(args, "transition", None)
    dest = transition or src
    try:
        # Unconditional: an append-only record must stay immutable whether or
        # not this call is even attempting a lifecycle transition.
        reject_append_only_mutation(record_def)
        if transition:
            reject_supersede_via_update(record_def, dest)
            check_transition(record_def, src, dest)
    except ValidationError as exc:
        if "append_with_audit" in str(exc):
            err_type = "append_only"
        elif "supersede operation" in str(exc):
            err_type = "use_supersede"
        else:
            err_type = "invalid_transition"
        return {"error": err_type, "message": str(exc), "from": src, "to": dest}, EXIT_TRANSITION
    try:
        body_given, body_text = _resolve_body(args)
    except _BodyArgError as exc:
        return {"error": "invalid_body", "message": str(exc)}, EXIT_ERROR
    record = dict(old)
    record["lifecycle_state"] = dest
    record["recorded_at"] = _now()
    record["identity"] = _resolve_identity(args)
    if requires_dimension(record_def, "epistemic_status") and dest in {
        "asserted",
        "supported",
        "disputed",
        "refuted",
        "retracted",
    }:
        record["epistemic_status"] = dest
    if body_given:
        record["body"] = body_text
    if args.payload:
        record["payload"] = dict(record.get("payload", {}))
        record["payload"].update(_load_payload(args.payload))
    if getattr(args, "rel", None):
        record["relationships"] = dict(record.get("relationships") or {})
        for rel_type, targets in _parse_rels(args.rel).items():
            existing = list(record["relationships"].get(rel_type) or [])
            for target in targets:
                if target not in existing:
                    existing.append(target)
            record["relationships"][rel_type] = existing
    try:
        validate_record(contract, record, {item["id"] for item in store.iter_records()})
    except ValidationError as exc:
        return {"error": "validation", "message": str(exc)}, EXIT_VALIDATION
    archive_prior = old if requires_history(record_def) else None
    try:
        stored = store.write_record(
            record,
            expected_revision=_resolve_expected_revision(args.expected_revision, old),
            archive_prior=archive_prior,
        )
    except StaleWriteError as exc:
        return {"error": "stale_write", "message": str(exc)}, EXIT_STALE
    return {"ok": True, "op": "update", "record": stored}, EXIT_OK


def cmd_update(args: argparse.Namespace) -> int:
    payload, code = _do_update(args)
    _emit_json(payload)
    return code


def _do_supersede(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _store_open_error(exc)
    defs = record_defs(contract)
    try:
        old = store.read_record(args.type, args.id)
    except StoreError as exc:
        return {"error": "not_found", "message": str(exc)}, EXIT_ERROR
    record_def = defs[old["record_type"]]
    try:
        reject_append_only_mutation(record_def)
        check_transition(record_def, old["lifecycle_state"], "superseded")
    except ValidationError as exc:
        err_type = "append_only" if "append_with_audit" in str(exc) else "invalid_transition"
        return {"error": err_type, "message": str(exc)}, EXIT_TRANSITION

    try:
        body_given, body_text = _resolve_body(args)
    except _BodyArgError as exc:
        return {"error": "invalid_body", "message": str(exc)}, EXIT_ERROR
    new_payload = dict(old.get("payload", {}))
    new_payload.update(_load_payload(args.payload))
    new_id = store.new_id()
    new_record = _base_record(
        old["record_type"],
        record_def,
        subject=old["subject"],
        stewardship=old.get("stewardship") or "agent",
        payload=new_payload,
        record_id=new_id,
        relationships={"supersedes": [old["id"]]},
        body=body_text if body_given else old.get("body", ""),
        identity=_resolve_identity(args),
    )
    records = list(store.iter_records())
    try:
        _supersede_preflight(contract, store, old, new_record, records)
    except ValidationError as exc:
        return {"error": "validation", "message": str(exc)}, EXIT_VALIDATION

    old_updated = dict(old)
    old_updated["lifecycle_state"] = "superseded"
    old_updated["recorded_at"] = _now()
    old_updated["identity"] = _resolve_identity(args)
    archive_prior = old if requires_history(record_def) else None
    try:
        predecessor = store.write_record(
            old_updated,
            expected_revision=_resolve_expected_revision(args.expected_revision, old),
            archive_prior=archive_prior,
        )
        stored = store.create_record(new_record)
    except StaleWriteError as exc:
        return {"error": "stale_write", "message": str(exc)}, EXIT_STALE
    return {"ok": True, "op": "supersede", "record": stored, "predecessor": predecessor}, EXIT_OK


def cmd_supersede(args: argparse.Namespace) -> int:
    payload, code = _do_supersede(args)
    _emit_json(payload)
    return code


def cmd_get(args: argparse.Namespace) -> int:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    defs = record_defs(contract)
    type_arg = getattr(args, "type", None)
    if not type_arg:
        # Ids are globally unique and opaque -- a caller that already has one
        # shouldn't need to also know (or re-derive) its type.
        record = _find_record_by_id(store, defs, args.id)
        if record is None:
            _emit_json({"error": "not_found", "message": f"unknown record: {args.id}"})
            return EXIT_ERROR
        _emit_json(record)
        return EXIT_OK
    try:
        record = store.read_record(type_arg, args.id)
    except StoreError as exc:
        message = str(exc)
        if not message.startswith("unknown record:"):
            # Not a "right type, wrong/missing id" case -- e.g. an unsafe or
            # malformed type string -- surface it exactly as read_record raised it.
            raise
        other = _find_record_by_id(store, defs, args.id)
        if other is not None:
            _emit_json(
                {
                    "error": "wrong_type",
                    "message": f"record {args.id} is {other['record_type']!r}, not {type_arg!r}",
                    "actual_type": other["record_type"],
                }
            )
            return EXIT_ERROR
        _emit_json({"error": "not_found", "message": message})
        return EXIT_ERROR
    _emit_json(record)
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    resolved_type = None
    if args.type:
        resolved_type, err = _resolve_record_type(record_defs(contract), args.type)
        if err is not None:
            _emit_json(err)
            return EXIT_VALIDATION
    try:
        where_filters = parse_where(args.where)
        grep = compile_grep(args.grep)
    except QueryError as exc:
        _emit_json({"error": "invalid_query", "message": str(exc)})
        return EXIT_ERROR
    try:
        # Derivation (e.g. `ready`) needs the whole record set -- a dependency
        # can name a record of any type/state, so filtering before deriving
        # would misreport real targets as dangling. Type/state filtering
        # happens locally afterward instead of via store.list_records.
        records = list(store.iter_records())
    except StoreError as exc:
        _emit_json({"error": "store", "message": str(exc)})
        return EXIT_ERROR
    derived_map = compute_derived(records, contract)
    records = attach_derived_all(records, derived_map)
    if resolved_type:
        records = [record for record in records if record["record_type"] == resolved_type]
    if args.state:
        records = [record for record in records if record["lifecycle_state"] == args.state]
    matched = [
        record
        for record in records
        if record_matches(
            record,
            where_filters=where_filters,
            subject=args.subject,
            grep=grep,
            since=args.since,
            until=args.until,
            has_inbound_types=args.has_inbound,
        )
    ]
    if args.order_by == "recorded_at":
        matched = order_by_recorded_at(matched)
    out_records = matched if args.full else [summarize(record, grep=grep) for record in matched]
    _emit_json({"records": out_records, "count": len(matched)})
    return EXIT_OK


def _do_correct(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _store_open_error(exc)
    defs = record_defs(contract)
    try:
        old = store.read_record(args.type, args.id)
    except StoreError as exc:
        return {"error": "not_found", "message": str(exc)}, EXIT_ERROR
    record_def = defs[old["record_type"]]
    if record_def.get("correction") != "successor_record":
        return {
            "error": "not_correctable",
            "message": f"{old['record_type']} does not use successor-record correction",
        }, EXIT_VALIDATION
    try:
        body_given, body_text = _resolve_body(args)
    except _BodyArgError as exc:
        return {"error": "invalid_body", "message": str(exc)}, EXIT_ERROR
    new_payload = dict(old.get("payload") or {})
    new_payload.update(_load_payload(args.payload))
    new_id = store.new_id()
    new_record = _base_record(
        old["record_type"],
        record_def,
        subject=args.subject or old["subject"],
        stewardship=old.get("stewardship") or args.steward or "agent",
        payload=new_payload,
        record_id=new_id,
        relationships={"corrects": [old["id"]]},
        body=body_text if body_given else old.get("body", ""),
        identity=_resolve_identity(args),
    )
    known_ids = {item["id"] for item in store.iter_records()} | {new_id}
    try:
        validate_record(contract, new_record, known_ids)
    except ValidationError as exc:
        return {"error": "validation", "message": str(exc)}, EXIT_VALIDATION
    stored = _persist_new(store, record_def, new_record)
    return {"ok": True, "op": "correct", "record": stored, "predecessor": old}, EXIT_OK


def cmd_correct(args: argparse.Namespace) -> int:
    payload, code = _do_correct(args)
    _emit_json(payload)
    return code


def _do_contradict(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _store_open_error(exc)
    defs = record_defs(contract)
    try:
        old = store.read_record(args.type, args.id)
    except StoreError as exc:
        return {"error": "not_found", "message": str(exc)}, EXIT_ERROR
    record_def = defs[old["record_type"]]
    if record_def.get("contradiction") != "separate_record":
        return {
            "error": "not_contradictable",
            "message": f"{old['record_type']} does not use separate-record contradiction",
        }, EXIT_VALIDATION
    payload = _load_payload(args.payload)
    subject = args.subject or payload.get("subject")
    if not subject:
        return {"error": "missing_subject"}, EXIT_ERROR
    try:
        body_given, body_text = _resolve_body(args)
    except _BodyArgError as exc:
        return {"error": "invalid_body", "message": str(exc)}, EXIT_ERROR
    new_id = store.new_id()
    new_record = _base_record(
        old["record_type"],
        record_def,
        subject=subject,
        stewardship=args.steward or old.get("stewardship") or "agent",
        payload=payload,
        record_id=new_id,
        # A contradicting record is a counter-claim, not a revision of the original,
        # so it must not inherit prose asserting what it disputes.
        body=body_text,
        identity=_resolve_identity(args),
    )
    updated = dict(old)
    updated["recorded_at"] = _now()
    updated["identity"] = _resolve_identity(args)
    rels = dict(updated.get("relationships") or {})
    targets = list(rels.get("contradicted_by") or [])
    if new_id not in targets:
        targets.append(new_id)
    rels["contradicted_by"] = targets
    updated["relationships"] = rels
    if args.transition:
        try:
            check_transition(record_def, old["lifecycle_state"], args.transition)
        except ValidationError as exc:
            return {"error": "invalid_transition", "message": str(exc)}, EXIT_TRANSITION
        updated["lifecycle_state"] = args.transition
        if requires_dimension(record_def, "epistemic_status"):
            updated["epistemic_status"] = args.transition
    known_ids = {item["id"] for item in store.iter_records()} | {new_id}
    try:
        validate_record(contract, new_record, known_ids)
        validate_record(contract, updated, known_ids)
    except ValidationError as exc:
        return {"error": "validation", "message": str(exc)}, EXIT_VALIDATION
    archive_prior = old if requires_history(record_def) else None
    try:
        stored = _persist_new(store, record_def, new_record)
        predecessor = store.write_record(
            updated,
            expected_revision=_resolve_expected_revision(args.expected_revision, old),
            archive_prior=archive_prior,
        )
    except StaleWriteError as exc:
        return {"error": "stale_write", "message": str(exc)}, EXIT_STALE
    return {"ok": True, "op": "contradict", "record": stored, "predecessor": predecessor}, EXIT_OK


def cmd_contradict(args: argparse.Namespace) -> int:
    payload, code = _do_contradict(args)
    _emit_json(payload)
    return code


_APPLY_OPS = {
    "create": _do_create,
    "update": _do_update,
    "supersede": _do_supersede,
    "correct": _do_correct,
    "contradict": _do_contradict,
}


def _op_args(base: argparse.Namespace, op: dict[str, Any]) -> argparse.Namespace:
    """Build a synthetic Namespace for one `apply` line, reusing the same
    _do_* functions the direct subcommands call -- store/contract come from
    the outer invocation, everything else from the op's own JSON."""
    payload = op.get("payload")
    return argparse.Namespace(
        store=base.store,
        contract=base.contract,
        type=op.get("type"),
        id=op.get("id"),
        subject=op.get("subject"),
        steward=op.get("steward"),
        identity=op.get("identity"),
        payload=json.dumps(payload) if payload is not None else None,
        rel=op.get("rel") or [],
        body=op.get("body"),
        body_file=op.get("body_file"),
        transition=op.get("transition"),
        expected_revision=op.get("expected_revision"),
    )


def cmd_apply(args: argparse.Namespace) -> int:
    """Run many mutation ops from newline-delimited JSON in one process,
    instead of one CLI invocation (one process spawn) per record.

    Failure semantics are continue-and-report, not all-or-nothing: the store
    already offers no cross-record transaction (see EXPECTED_BACKEND_GUARANTEES
    in contract.py -- "multi_record_write": "non_transactional"), so pretending
    a batch of independent single-record writes is atomic would be a lie: a
    crash mid-batch already leaves partial state under `create`/`update` run
    one-by-one, and this call is just those same writes sharing a process.
    Every line's own ok/error result is reported so a caller can tell exactly
    which lines landed. `capture` is excluded -- its bundle-wide compensating
    rollback doesn't compose with per-line continue-and-report.
    """
    input_arg = getattr(args, "input", "-") or "-"
    text = sys.stdin.read() if input_arg == "-" else Path(input_arg).read_text()
    results: list[dict[str, Any]] = []
    failed = 0
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            op = json.loads(line)
        except json.JSONDecodeError as exc:
            results.append({"ok": False, "line": line_no, "error": "json", "message": str(exc)})
            failed += 1
            continue
        verb = op.get("op") if isinstance(op, dict) else None
        handler = _APPLY_OPS.get(verb)
        if handler is None:
            results.append(
                {
                    "ok": False,
                    "line": line_no,
                    "op": verb,
                    "error": "unknown_op",
                    "message": f"unsupported op {verb!r}; expected one of {sorted(_APPLY_OPS)}",
                }
            )
            failed += 1
            continue
        try:
            result, code = handler(_op_args(args, op))
        except (StoreError, ContractError, ValidationError) as exc:
            result, code = {"error": "internal", "message": str(exc)}, EXIT_ERROR
        result = dict(result)
        result["line"] = line_no
        results.append(result)
        if code != EXIT_OK:
            failed += 1
    applied = len(results) - failed
    _emit_json(
        {
            "ok": failed == 0,
            "op": "apply",
            "applied": applied,
            "failed": failed,
            "results": results,
        }
    )
    return EXIT_OK if failed == 0 else EXIT_ERROR


def _capture_create_order(bundle: dict[str, Any]) -> list[str]:
    pending = list(bundle["records"])
    ordered: list[str] = []
    while pending:
        sources_waiting = {
            link["from"]
            for link in bundle.get("relationships") or []
            if link["to"] not in ordered
        }
        ready = [item for item in pending if item not in sources_waiting]
        if not ready:
            ready = [pending[0]]
        chosen = ready[0]
        pending.remove(chosen)
        ordered.append(chosen)
    return ordered


class _CaptureFailure(Exception):
    """Carries a failed part's error payload out of the create loop so the
    caller can roll back whatever the bundle already persisted before
    reporting it -- see _rollback_capture."""

    def __init__(self, payload: dict[str, Any], exit_code: int):
        super().__init__(payload.get("message") or payload.get("error"))
        self.payload = payload
        self.exit_code = exit_code


def _rollback_capture(
    store: Store, defs: dict[str, Any], created: dict[str, list[dict[str, Any]]]
) -> None:
    """Undo every record this capture call persisted before it failed.

    This is a best-effort compensating delete, not a transaction: a hard
    crash (not a raised exception) between two of the already-written
    records is still possible and is not covered, and another writer can in
    principle observe the partial bundle before rollback runs.
    """
    for record_type, records in created.items():
        record_def = defs.get(record_type)
        append_only = record_def is not None and is_append_only(record_def)
        for record in records:
            if append_only:
                store.delete_history_snapshot(record_type, record["id"], record["revision"])
            store.delete_record_file(record_type, record["id"])


def cmd_capture(args: argparse.Namespace) -> int:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    try:
        bundle = bundle_by_id(contract, args.bundle)
    except ContractError as exc:
        _emit_json({"error": "unknown_bundle", "message": str(exc)})
        return EXIT_VALIDATION
    try:
        parts = json.loads(args.records)
    except json.JSONDecodeError as exc:
        _emit_json({"error": "json", "message": str(exc)})
        return EXIT_ERROR
    if not isinstance(parts, list):
        _emit_json({"error": "invalid_records", "message": "records must be a JSON list"})
        return EXIT_ERROR
    by_type: dict[str, list[dict[str, Any]]] = {}
    for part in parts:
        if not isinstance(part, dict) or "type" not in part:
            _emit_json({"error": "invalid_records", "message": "each record needs type"})
            return EXIT_ERROR
        by_type.setdefault(part["type"], []).append(part)
    expected = set(bundle["records"])
    if set(by_type) != expected:
        _emit_json(
            {
                "error": "bundle_mismatch",
                "message": f"bundle {bundle['id']} requires {sorted(expected)}",
            }
        )
        return EXIT_VALIDATION
    defs = record_defs(contract)
    created: dict[str, list[dict[str, Any]]] = {}
    try:
        for record_type in _capture_create_order(bundle):
            for part in by_type[record_type]:
                payload = part.get("payload") or {}
                subject = part.get("subject") or payload.get("subject")
                if not subject:
                    raise _CaptureFailure(
                        {"error": "missing_subject", "type": record_type}, EXIT_ERROR
                    )
                body_value = part.get("body", "")
                if body_value is None:
                    body_value = ""
                if not isinstance(body_value, str):
                    raise _CaptureFailure(
                        {
                            "error": "invalid_records",
                            "message": f"body for {record_type} must be a string",
                        },
                        EXIT_ERROR,
                    )
                relationships: dict[str, list[str]] = {}
                for link in bundle.get("relationships") or []:
                    if link["from"] != record_type:
                        continue
                    targets = created.get(link["to"]) or []
                    if not targets:
                        raise _CaptureFailure(
                            {
                                "error": "bundle_order",
                                "message": f"cannot link {record_type} before {link['to']}",
                            },
                            EXIT_ERROR,
                        )
                    for target in targets:
                        relationships.setdefault(link["type"], []).append(target["id"])
                record_id = store.new_id()
                record = _base_record(
                    record_type,
                    defs[record_type],
                    subject=subject,
                    stewardship=part.get("steward") or "agent",
                    payload=payload,
                    record_id=record_id,
                    relationships=relationships or None,
                    body=body_value,
                    identity=part.get("identity") or _resolve_identity(args),
                )
                known_ids = {item["id"] for item in store.iter_records()} | {record_id}
                try:
                    validate_record(contract, record, known_ids)
                except ValidationError as exc:
                    raise _CaptureFailure(
                        {"error": "validation", "message": str(exc)}, EXIT_VALIDATION
                    ) from exc
                stored = _persist_new(store, defs[record_type], record)
                created.setdefault(record_type, []).append(stored)
    except _CaptureFailure as exc:
        _rollback_capture(store, defs, created)
        _emit_json(exc.payload)
        return exc.exit_code
    except StoreError as exc:
        _rollback_capture(store, defs, created)
        _emit_json({"error": "store", "message": str(exc)})
        return EXIT_ERROR
    except Exception:
        # Any failure leaving records behind must roll back, not just the
        # ones we anticipated -- an OSError mid-bundle orphans them otherwise.
        _rollback_capture(store, defs, created)
        raise
    records_out = {
        record_type: (records[0] if len(records) == 1 else records)
        for record_type, records in created.items()
    }
    _emit_json(
        {
            "ok": True,
            "op": "capture",
            "bundle": bundle["id"],
            "records": records_out,
        }
    )
    return EXIT_OK


def cmd_handoff(args: argparse.Namespace) -> int:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    records = list(store.iter_records())
    records = attach_derived_all(records, compute_derived(records, contract))
    try:
        markdown = generate_handoff(contract, records, store_root=_view_store_root(store))
    except ContractError as exc:
        _emit_json({"error": "view_not_found", "message": str(exc)})
        return EXIT_VALIDATION
    if args.out:
        try:
            out_path = _safe_out_path(store, args.out)
        except ValidationError:
            _emit_json({"error": "unsafe_output_path", "path": args.out})
            return EXIT_VALIDATION
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown)
        _emit_json({"status": "ok", "path": str(out_path), "derived": True})
    else:
        print(markdown)
    return EXIT_OK


def cmd_view(args: argparse.Namespace) -> int:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    records = list(store.iter_records())
    records = attach_derived_all(records, compute_derived(records, contract))
    if args.check:
        try:
            rendered_text = Path(args.check).read_text()
        except OSError as exc:
            _emit_json({"error": "unreadable_check_path", "path": args.check, "message": str(exc)})
            return EXIT_ERROR
        if args.id:
            try:
                view_by_id(contract, args.id)
            except ContractError as exc:
                _emit_json({"error": "view_not_found", "message": str(exc)})
                return EXIT_VALIDATION
            view_ids = [args.id]
            sections = [rendered_text]
        else:
            view_ids = [view["id"] for view in contract.get("views") or []]
            sections = rendered_text.split("\n---\n\n")
        if len(sections) != len(view_ids):
            _emit_json(
                {
                    "error": "check_shape_mismatch",
                    "expected_views": len(view_ids),
                    "found_sections": len(sections),
                }
            )
            return EXIT_ERROR
        stale = [
            view_id
            for view_id, section in zip(view_ids, sections)
            if view_is_stale(contract, view_id, records, section)
        ]
        if stale:
            _emit_json({"status": "stale", "views": stale})
            return EXIT_STALE
        _emit_json({"status": "fresh", "views": view_ids})
        return EXIT_OK
    if args.id:
        try:
            view_by_id(contract, args.id)
            markdown = generate_view(
                contract, args.id, records, store_root=_view_store_root(store)
            )
        except ContractError as exc:
            _emit_json({"error": "view_not_found", "message": str(exc)})
            return EXIT_VALIDATION
        rendered = {args.id: markdown}
    else:
        rendered = generate_all_views(contract, records, store_root=_view_store_root(store))
        markdown = "\n---\n\n".join(rendered.values())
    if args.out:
        try:
            out_path = _safe_out_path(store, args.out)
        except ValidationError:
            _emit_json({"error": "unsafe_output_path", "path": args.out})
            return EXIT_VALIDATION
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown)
        _emit_json({"status": "ok", "path": str(out_path), "views": list(rendered), "derived": True})
        return EXIT_OK
    print(markdown)
    return EXIT_OK


# Roles whose records describe the whole effort, not one work-item, so they
# scope by payload.effort instead of by subject (see _brief_in_scope).
_BRIEF_EFFORT_SCOPED_ROLES = frozenset({"constraint", "position"})

_BRIEF_ROLE_TITLES = {
    "work": "Work Item",
    "acceptance": "Acceptance Criteria",
    "finding": "Findings",
    "constraint": "Constraints",
    "position": "Position",
    "amendment": "Unapplied Amendments",
}


def _brief_view(contract: dict[str, Any]) -> dict[str, Any] | None:
    return next((view for view in contract.get("views") or [] if view.get("name") == "brief"), None)


def _brief_title(role_name: str) -> str:
    return _BRIEF_ROLE_TITLES.get(role_name, role_name.replace("-", " ").title())


def _brief_in_scope(
    role_name: str, subject: str, effort: str, record: dict[str, Any]
) -> bool:
    """One extra filter per role, layered on top of its own contract-declared
    selection -- the piece record_matches_selection has no vocabulary for:
    which work-item a record belongs to. `work` is the anchor (exact subject
    match); `constraint`/`position` describe the whole effort rather than one
    work-item, so they scope by payload.effort instead. Every other role
    (including one a project renames or adds later) falls back to the
    subject-prefix link validation.subject_related already defines, rather
    than inventing a second, differently-tuned correlation rule.
    """
    if role_name == "work":
        return record.get("subject") == subject
    if role_name in _BRIEF_EFFORT_SCOPED_ROLES:
        return (record.get("payload") or {}).get("effort") == effort
    return subject_related(subject, record.get("subject") or "")


def _brief_record_block(record: dict[str, Any], role: dict[str, Any]) -> str:
    payload = record.get("payload") or {}
    fields = [field for field in (role.get("requires_payload") or []) if field != "subject"]
    bits = [f"**{field}**: {payload[field]}" for field in fields if payload.get(field) not in (None, "")]
    if record.get("lifecycle_state"):
        bits.append(f"state: {record['lifecycle_state']}")
    lines = [f"### {record.get('subject')}"]
    if bits:
        lines.append("; ".join(bits))
    # Payload fields are the index; the body is the prose an executor actually
    # needs verbatim (criterion text, finding evidence, constraint basis) --
    # a one-line summary here would recreate the hand-copying this exists to end.
    body = (record.get("body") or "").strip()
    if body:
        lines.append("")
        lines.append(body)
    lines.append("")
    return "\n".join(lines)


def _brief_section(role: dict[str, Any], records: list[dict[str, Any]]) -> str:
    lines = [f"## {_brief_title(role['name'])}", ""]
    if not records:
        lines.append("_None._")
        lines.append("")
        return "\n".join(lines)
    ordered = sorted(records, key=lambda r: (r.get("subject") or "", r.get("id") or ""))
    for record in ordered:
        lines.append(_brief_record_block(record, role))
    return "\n".join(lines)


def cmd_brief(args: argparse.Namespace) -> int:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    view = _brief_view(contract)
    if view is None:
        _emit_json({"error": "view_not_found", "message": "no view named 'brief' in contract"})
        return EXIT_VALIDATION
    records = list(store.iter_records())
    records = attach_derived_all(records, compute_derived(records, contract))
    subject = args.subject
    work_role = next((role for role in view["roles"] if role["name"] == "work"), None)
    work_item = None
    if work_role is not None:
        work_item = next(
            (
                record
                for record in records
                if record["record_type"] == work_role["occupant"]
                and record.get("subject") == subject
                and record_matches_selection(record, work_role["selection"])
            ),
            None,
        )
    if work_item is None:
        _emit_json({"error": "not_found", "message": f"no work item found for subject {subject!r}"})
        return EXIT_ERROR
    effort = (work_item.get("payload") or {}).get("effort", "")
    sections = []
    for role in view["roles"]:
        selected = [
            record
            for record in records
            if record["record_type"] == role["occupant"]
            and record_matches_selection(record, role["selection"])
            and _brief_in_scope(role["name"], subject, effort, record)
        ]
        sections.append(_brief_section(role, selected))
    markdown = "\n".join(
        [
            f"# Brief: {subject}",
            "",
            "> Derived brief — not authoritative. Composed on demand from "
            f"`{view['id']}`; edit records, not this file.",
            "",
            *sections,
        ]
    )
    if args.out:
        try:
            out_path = _safe_out_path(store, args.out)
        except ValidationError:
            _emit_json({"error": "unsafe_output_path", "path": args.out})
            return EXIT_VALIDATION
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown)
        _emit_json({"status": "ok", "path": str(out_path), "derived": True})
        return EXIT_OK
    print(markdown)
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    errors: list[str] = []
    records = load_records_for_validation(store.root, errors)
    errors.extend(validate_store(contract, records, store_root=store.root))
    if errors:
        _emit_json({"status": "invalid", "errors": errors})
        return EXIT_VALIDATION
    if getattr(args, "strict", False):
        warnings = validate_strict(records, record_defs(contract))
        if warnings:
            _emit_json({"status": "valid_with_warnings", "warnings": warnings})
            return EXIT_STRICT
    _emit_json({"status": "valid", "records": len(records)})
    return EXIT_OK


# Session-start surfaces constraint statements only, not whole records, and
# caps how many -- a design with dozens of standing constraints still needs a
# bounded injection, not a full dump.
MAX_HOOK_CONSTRAINTS = 8


def _hook_focused_effort(
    contract: dict[str, Any], records: list[dict[str, Any]]
) -> str | None:
    """The effort to surface constraints for, read off whichever active
    record occupies the handoff view's own 'position' role -- a design
    without that role, or without an active position yet, gets no
    constraint injection instead of a guess."""
    try:
        view = handoff_view(contract)
    except ContractError:
        return None
    role = next((r for r in view["roles"] if r["name"] == "position"), None)
    if role is None:
        return None
    for record in records:
        if record["record_type"] == role["occupant"] and record_matches_selection(
            record, role["selection"]
        ):
            effort = (record.get("payload") or {}).get("effort")
            if effort:
                return effort
    return None


def _hook_constraint_role(contract: dict[str, Any]) -> dict[str, Any] | None:
    for view in contract.get("views") or []:
        for role in view.get("roles") or []:
            if role["name"] == "constraint":
                return role
    return None


def _hook_constraints(
    contract: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, Any]:
    role = _hook_constraint_role(contract)
    if role is None:
        return {"items": [], "total": 0}
    effort = _hook_focused_effort(contract, records)
    if not effort:
        return {"items": [], "total": 0}
    matches = [
        record
        for record in records
        if record["record_type"] == role["occupant"]
        and record_matches_selection(record, role["selection"])
        and (record.get("payload") or {}).get("effort") == effort
    ]
    matches.sort(key=lambda r: r.get("subject") or "")
    items = [
        {
            "subject": record.get("subject"),
            "statement": (record.get("payload") or {}).get("statement", ""),
        }
        for record in matches[:MAX_HOOK_CONSTRAINTS]
    ]
    return {"items": items, "total": len(matches)}


def cmd_hook_start(args: argparse.Namespace) -> int:
    store = Store(Path(args.store))
    if store.is_absent():
        _emit_json({"handoff": "", "records": 0, "note": "store not initialized"})
        return EXIT_OK
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    records = list(store.iter_records())
    records = attach_derived_all(records, compute_derived(records, contract))
    views = generate_all_views(contract, records, store_root=_view_store_root(store))
    handoff_id = next((view_id for view_id in views if view_id.endswith(":handoff")), None)
    _emit_json(
        {
            "handoff": views.get(handoff_id, "") if handoff_id else "",
            "views": views,
            "constraints": _hook_constraints(contract, records),
            "records": len(records),
            "derived": True,
        }
    )
    return EXIT_OK


def cmd_hook_stop(args: argparse.Namespace) -> int:
    try:
        assert_git_context(Path(args.root))
    except GitContextError as exc:
        _emit_json({"error": "git_context", "message": str(exc)})
        return EXIT_ERROR
    store = Store(Path(args.store))
    if store.is_absent():
        _emit_json({"status": "skipped", "reason": "store not initialized"})
        return EXIT_OK
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    errors: list[str] = []
    records = load_records_for_validation(store.root, errors)
    errors.extend(validate_store(contract, records, store_root=store.root))
    if errors:
        _emit_json({"status": "invalid", "errors": errors})
        return EXIT_VALIDATION
    views_dir = store.root / "views"
    if views_dir.is_dir():
        records_with_derived = attach_derived_all(records, compute_derived(records, contract))
        stale = [
            view["id"]
            for view in contract.get("views") or []
            if (views_dir / view_file_name(view["id"])).is_file()
            and view_is_stale(
                contract,
                view["id"],
                records_with_derived,
                (views_dir / view_file_name(view["id"])).read_text(),
            )
        ]
        if stale:
            _emit_json({"status": "stale_views", "views": stale})
            return EXIT_STALE
    _emit_json({"status": "valid", "records": len(records)})
    return EXIT_OK


def _require_contract(args: argparse.Namespace) -> dict[str, Any]:
    return load_contract(Path(args.contract))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Contract-driven artifact runtime")
    parser.add_argument("--root", default=None, help="Project root (default: cwd)")
    parser.add_argument("--store", default=None, help="Store root path")
    parser.add_argument(
        "--contract",
        default=None,
        help="Resolved contract JSON path (default: store meta or .artifacts/resolved-contract.json)",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        dest="read_only",
        help="Refuse every mutating command (create/update/supersede/correct/"
        "contradict/capture/apply/init); reads still work "
        "(default: $ADAPTIVE_ARTIFACTS_READONLY=1)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_resolve = sub.add_parser("resolve", help="Materialize .artifacts/resolved-contract.json")
    p_resolve.add_argument("--design", help="Project design JSON path")
    p_resolve.add_argument("--out", help="Resolved contract output path")

    p_lock = sub.add_parser("lock", help="Print source_lock for catalog, traits, and backends")
    p_lock.set_defaults(func=cmd_lock)

    p_init = sub.add_parser("init", help="Initialize store (requires git context)")
    p_init.set_defaults(func=cmd_init)

    p_create = sub.add_parser("create", help="Create a new record")
    p_create.add_argument("--type", required=True, help="Qualified record type")
    p_create.add_argument("--subject", help="Record subject")
    p_create.add_argument("--steward", help="Steward identifier")
    p_create.add_argument(
        "--identity", help="Writer identity (default: $ARTIFACTS_IDENTITY or 'unknown')"
    )
    p_create.add_argument("--payload", help="JSON payload object")
    p_create.add_argument(
        "--rel",
        action="append",
        default=[],
        help="Relationship as type:target_id (repeatable)",
    )
    p_create.add_argument("--body", help="Markdown body text")
    p_create.add_argument("--body-file", help="Read Markdown body from file ('-' for stdin)")
    p_create.set_defaults(func=cmd_create)

    p_update = sub.add_parser("update", help="Transition or mutate an existing record")
    p_update.add_argument("--type", required=True)
    p_update.add_argument("--id", required=True)
    p_update.add_argument(
        "--transition",
        help="Target lifecycle state; omit to patch payload/body/relationships "
        "in place without changing lifecycle state",
    )
    p_update.add_argument(
        "--expected-revision",
        required=True,
        help="Exact revision string, or '@current' to re-read and use whatever is current",
    )
    p_update.add_argument(
        "--identity", help="Writer identity (default: $ARTIFACTS_IDENTITY or 'unknown')"
    )
    p_update.add_argument("--payload", help="JSON payload updates")
    p_update.add_argument(
        "--rel",
        action="append",
        default=[],
        help="Relationship as type:target_id (repeatable)",
    )
    p_update.add_argument("--body", help="Markdown body text (replaces the current body)")
    p_update.add_argument("--body-file", help="Read Markdown body from file ('-' for stdin)")
    p_update.set_defaults(func=cmd_update)

    p_sup = sub.add_parser("supersede", help="Supersede with a new record id")
    p_sup.add_argument("--type", required=True)
    p_sup.add_argument("--id", required=True)
    p_sup.add_argument(
        "--expected-revision",
        required=True,
        help="Exact revision string, or '@current' to re-read and use whatever is current",
    )
    p_sup.add_argument("--payload", help="JSON payload for successor")
    p_sup.add_argument(
        "--identity", help="Writer identity (default: $ARTIFACTS_IDENTITY or 'unknown')"
    )
    p_sup.add_argument(
        "--body", help="Markdown body for successor (default: carries the predecessor's body forward)"
    )
    p_sup.add_argument("--body-file", help="Read Markdown body from file ('-' for stdin)")
    p_sup.set_defaults(func=cmd_supersede)

    p_correct = sub.add_parser("correct", help="Append a correcting successor; original stays recorded")
    p_correct.add_argument("--type", required=True)
    p_correct.add_argument("--id", required=True)
    p_correct.add_argument("--payload", help="JSON payload overrides for successor")
    p_correct.add_argument("--subject", help="Successor subject (defaults to original)")
    p_correct.add_argument("--steward", help="Steward identifier")
    p_correct.add_argument(
        "--identity", help="Writer identity (default: $ARTIFACTS_IDENTITY or 'unknown')"
    )
    p_correct.add_argument(
        "--body", help="Markdown body for successor (default: carries the predecessor's body forward)"
    )
    p_correct.add_argument("--body-file", help="Read Markdown body from file ('-' for stdin)")
    p_correct.set_defaults(func=cmd_correct)

    p_contradict = sub.add_parser(
        "contradict", help="Create a contradicting record and link the original"
    )
    p_contradict.add_argument("--type", required=True)
    p_contradict.add_argument("--id", required=True)
    p_contradict.add_argument(
        "--expected-revision",
        required=True,
        help="Exact revision string, or '@current' to re-read and use whatever is current",
    )
    p_contradict.add_argument("--subject", help="Subject of the contradicting record")
    p_contradict.add_argument("--payload", required=True, help="JSON payload for the new record")
    p_contradict.add_argument("--transition", help="Optional lifecycle transition on the original")
    p_contradict.add_argument("--steward", help="Steward identifier")
    p_contradict.add_argument(
        "--identity", help="Writer identity (default: $ARTIFACTS_IDENTITY or 'unknown')"
    )
    p_contradict.add_argument(
        "--body",
        help="Markdown body for the contradicting record (default: carries the original's body forward)",
    )
    p_contradict.add_argument("--body-file", help="Read Markdown body from file ('-' for stdin)")
    p_contradict.set_defaults(func=cmd_contradict)

    p_capture = sub.add_parser("capture", help="Capture a bundle of records")
    p_capture.add_argument("--bundle", required=True, help="Qualified bundle id")
    p_capture.add_argument(
        "--records",
        required=True,
        help="JSON list of {type, subject, payload, body} objects (body is optional, default '')",
    )
    p_capture.add_argument(
        "--identity",
        help="Default writer identity for parts with no per-part 'identity' "
        "(default: $ARTIFACTS_IDENTITY or 'unknown')",
    )
    p_capture.set_defaults(func=cmd_capture)

    p_apply = sub.add_parser(
        "apply", help="Run many create/update/supersede/correct/contradict ops from NDJSON"
    )
    p_apply.add_argument(
        "input",
        nargs="?",
        default="-",
        help="NDJSON file of {op, type, id, ...} operations, or '-' for stdin (default '-')",
    )
    p_apply.set_defaults(func=cmd_apply)

    p_get = sub.add_parser("get", help="Fetch one record")
    p_get.add_argument(
        "--type",
        help="Qualified or short record type; ids are globally unique, so this "
        "is optional and only narrows a wrong-type mismatch from a not-found",
    )
    p_get.add_argument("--id", required=True)
    p_get.set_defaults(func=cmd_get)

    p_list = sub.add_parser("list", help="List records")
    p_list.add_argument("--type")
    p_list.add_argument("--state")
    p_list.add_argument(
        "--where",
        action="append",
        default=[],
        metavar="payload.<field>=<value>",
        help=(
            "Filter by payload.<field> or derived.<field> equality (repeatable; "
            "AND semantics). derived fields (e.g. derived.ready, derived.wave) are "
            "computed at read time, never stored. The value is JSON-decoded when "
            "possible (true/42/\"x\"), otherwise compared as a literal string."
        ),
    )
    p_list.add_argument(
        "--subject",
        help="Match records whose subject equals this value, or starts with it (exact-or-prefix)",
    )
    p_list.add_argument(
        "--grep",
        help="Case-insensitive regex match against the record body (not frontmatter fields)",
    )
    p_list.add_argument(
        "--full",
        action="store_true",
        help="Emit full records (including body) instead of the default compact summary",
    )
    p_list.add_argument("--since", help="Only records with recorded_at >= this ISO-8601 timestamp")
    p_list.add_argument("--until", help="Only records with recorded_at <= this ISO-8601 timestamp")
    p_list.add_argument(
        "--has-inbound",
        action="append",
        default=[],
        dest="has_inbound",
        metavar="<relationship_type>",
        help=(
            "Only records with at least one inbound relationship of this type "
            "(derived.referenced_by; repeatable, AND semantics)"
        ),
    )
    p_list.add_argument(
        "--order-by",
        choices=["recorded_at"],
        dest="order_by",
        help="Sort matched records (oldest recorded_at first; records missing it sort first)",
    )
    p_list.set_defaults(func=cmd_list)

    p_handoff = sub.add_parser("handoff", help="Generate derived handoff markdown")
    p_handoff.add_argument("--out", help="Optional output path under store")
    p_handoff.set_defaults(func=cmd_handoff)

    p_view = sub.add_parser("view", help="Generate a derived view from the contract")
    p_view.add_argument("--id", help="Qualified view id; omit to render all")
    p_view.add_argument("--out", help="Optional output path under store")
    p_view.add_argument(
        "--check",
        metavar="PATH",
        help="Compare an already-rendered view file's embedded digest against "
        "live store state instead of rendering (exit code %d if stale)" % EXIT_STALE,
    )
    p_view.set_defaults(func=cmd_view)

    p_brief = sub.add_parser(
        "brief", help="Compose a single work-item's brief from linked records"
    )
    p_brief.add_argument("subject", help="Work-item subject")
    p_brief.add_argument("--out", help="Optional output path under store")
    p_brief.set_defaults(func=cmd_brief)

    p_validate = sub.add_parser("validate", help="Validate store against contract")
    p_validate.add_argument(
        "--strict",
        action="store_true",
        help="Also warn on legal-but-suspicious shapes (distinct exit code, no effect on status)",
    )
    p_validate.set_defaults(func=cmd_validate)

    p_start = sub.add_parser("hook-start", help="Session-start hook adapter (read-only)")
    p_start.set_defaults(func=cmd_hook_start)

    p_stop = sub.add_parser("hook-stop", help="Session-stop hook adapter (validate only)")
    p_stop.set_defaults(func=cmd_hook_stop)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _apply_paths(args)
    if args.command in MUTATING_COMMANDS and _is_read_only(args):
        _emit_json(
            {
                "error": "read_only",
                "message": f"{args.command!r} is disabled: runtime is in read-only mode",
            }
        )
        return EXIT_ERROR
    if args.command == "resolve":
        return cmd_resolve(args)
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except StoreError as exc:
        _emit_json({"error": "store", "message": str(exc)})
        sys.exit(EXIT_ERROR)
    except json.JSONDecodeError as exc:
        _emit_json({"error": "json", "message": str(exc)})
        sys.exit(EXIT_ERROR)
    except ContractError as exc:
        _emit_json({"error": "contract", "message": str(exc)})
        sys.exit(EXIT_ERROR)
    except Exception as exc:
        _emit_json({"error": "internal", "message": f"{type(exc).__name__}: {exc}"})
        sys.exit(EXIT_ERROR)
