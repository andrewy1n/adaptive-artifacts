#!/usr/bin/env python3
"""Contract-driven artifact runtime."""

from __future__ import annotations

import argparse
import json
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
    initial_state,
    is_append_only,
    load_contract,
    record_defs,
    requires_dimension,
    requires_history,
    view_by_id,
)
from git_backend import GitContextError, assert_git_context
from handoff import generate_all_views, generate_handoff, generate_view
from store import (
    ContractBindingError,
    PartialStoreError,
    StaleWriteError,
    Store,
    StoreError,
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
    validate_record,
    validate_store,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_STALE = 2
EXIT_TRANSITION = 3
EXIT_VALIDATION = 4


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _emit_json(data: Any) -> None:
    print(json.dumps(data, indent=2))


def _load_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise StoreError("payload must be a JSON object")
    return data


def _handle_store_open_error(exc: Exception) -> int:
    if isinstance(exc, ContractBindingError):
        _emit_json({"error": "contract_drift", "message": str(exc)})
        return EXIT_VALIDATION
    if isinstance(exc, (StoreNotInitializedError, PartialStoreError)):
        _emit_json({"error": "store_not_ready", "message": str(exc)})
        return EXIT_ERROR
    raise exc


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
) -> dict[str, Any]:
    if isinstance(stewardship, str):
        stewardship = {"steward": stewardship}
    body: dict[str, Any] = {
        "id": record_id,
        "record_type": record_type,
        "base_kind": record_def["base_kind"],
        "subject": subject,
        "payload": payload,
        "lifecycle_state": lifecycle_state or initial_state(record_def),
        "relationships": relationships or {},
        "revision": "",
    }
    if requires_dimension(record_def, "stewardship"):
        body["stewardship"] = stewardship
    if requires_dimension(record_def, "epistemic_status"):
        body["epistemic_status"] = "asserted"
    if requires_dimension(record_def, "adoption_or_deontic_status"):
        body["adoption_or_deontic_status"] = "active"
    if requires_dimension(record_def, "time"):
        if record_def["base_kind"] == "claim":
            body["time"] = {"as_of": _now()}
        elif record_def["base_kind"] == "commitment":
            body["time"] = {"effective_time": payload.get("effective_time") or _now()}
        else:
            body["time"] = {
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
        body["provenance"] = {"sources": sources}
    return body


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
        store.archive_history(stored)
    return stored


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
        status = store.init(contract, contract_path.resolve())
    except (PartialStoreError, StoreError) as exc:
        _emit_json({"error": "init_rejected", "message": str(exc)})
        return EXIT_ERROR
    _emit_json({"status": status, "store": str(store.root)})
    return EXIT_OK


def cmd_create(args: argparse.Namespace) -> int:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    defs = record_defs(contract)
    record_type = args.type
    if record_type not in defs:
        _emit_json({"error": "unknown_type", "type": record_type})
        return EXIT_VALIDATION
    payload = _load_payload(args.payload)
    subject = args.subject or payload.get("subject")
    if not subject:
        _emit_json({"error": "missing_subject"})
        return EXIT_ERROR
    try:
        relationships = _parse_rels(getattr(args, "rel", None))
    except StoreError as exc:
        _emit_json({"error": "invalid_rel", "message": str(exc)})
        return EXIT_ERROR
    record_id = store.new_id()
    record = _base_record(
        record_type,
        defs[record_type],
        subject=subject,
        stewardship=args.steward or "agent",
        payload=payload,
        record_id=record_id,
        relationships=relationships or None,
    )
    known_ids = {item["id"] for item in store.iter_records()} | {record_id}
    try:
        validate_record(contract, record, known_ids)
    except ValidationError as exc:
        _emit_json({"error": "validation", "message": str(exc)})
        return EXIT_VALIDATION
    stored = _persist_new(store, defs[record_type], record)
    _emit_json({"status": "created", "record": stored})
    return EXIT_OK


def cmd_update(args: argparse.Namespace) -> int:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    defs = record_defs(contract)
    try:
        old = store.read_record(args.type, args.id)
    except StoreError as exc:
        _emit_json({"error": "not_found", "message": str(exc)})
        return EXIT_ERROR
    record_def = defs[old["record_type"]]
    src = old["lifecycle_state"]
    dest = args.transition
    try:
        reject_append_only_mutation(record_def)
        reject_supersede_via_update(record_def, dest)
        check_transition(record_def, src, dest)
    except ValidationError as exc:
        if "append_with_audit" in str(exc):
            err_type = "append_only"
        elif "supersede operation" in str(exc):
            err_type = "use_supersede"
        else:
            err_type = "invalid_transition"
        _emit_json({"error": err_type, "message": str(exc), "from": src, "to": dest})
        return EXIT_TRANSITION
    record = dict(old)
    record["lifecycle_state"] = dest
    if requires_dimension(record_def, "epistemic_status") and dest in {
        "asserted",
        "supported",
        "disputed",
        "refuted",
        "retracted",
    }:
        record["epistemic_status"] = dest
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
        _emit_json({"error": "validation", "message": str(exc)})
        return EXIT_VALIDATION
    archive_prior = old if requires_history(record_def) else None
    try:
        stored = store.write_record(
            record,
            expected_revision=args.expected_revision,
            archive_prior=archive_prior,
        )
    except StaleWriteError as exc:
        _emit_json({"error": "stale_write", "message": str(exc)})
        return EXIT_STALE
    _emit_json({"status": "updated", "record": stored})
    return EXIT_OK


def cmd_supersede(args: argparse.Namespace) -> int:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    defs = record_defs(contract)
    try:
        old = store.read_record(args.type, args.id)
    except StoreError as exc:
        _emit_json({"error": "not_found", "message": str(exc)})
        return EXIT_ERROR
    record_def = defs[old["record_type"]]
    try:
        reject_append_only_mutation(record_def)
        check_transition(record_def, old["lifecycle_state"], "superseded")
    except ValidationError as exc:
        err_type = "append_only" if "append_with_audit" in str(exc) else "invalid_transition"
        _emit_json({"error": err_type, "message": str(exc)})
        return EXIT_TRANSITION

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
    )
    records = list(store.iter_records())
    try:
        _supersede_preflight(contract, store, old, new_record, records)
    except ValidationError as exc:
        _emit_json({"error": "validation", "message": str(exc)})
        return EXIT_VALIDATION

    old_updated = dict(old)
    old_updated["lifecycle_state"] = "superseded"
    archive_prior = old if requires_history(record_def) else None
    try:
        store.write_record(
            old_updated,
            expected_revision=args.expected_revision,
            archive_prior=archive_prior,
        )
    except StaleWriteError as exc:
        _emit_json({"error": "stale_write", "message": str(exc)})
        return EXIT_STALE
    stored = store.create_record(new_record)
    _emit_json({"status": "superseded", "old": old["id"], "new": stored})
    return EXIT_OK


def cmd_get(args: argparse.Namespace) -> int:
    try:
        store, _contract = _open_store(args)
        record = store.read_record(args.type, args.id)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    except StoreError as exc:
        _emit_json({"error": "not_found", "message": str(exc)})
        return EXIT_ERROR
    _emit_json(record)
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    try:
        store, _contract = _open_store(args)
        records = store.list_records(record_type=args.type, lifecycle_state=args.state)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    except StoreError as exc:
        _emit_json({"error": "store", "message": str(exc)})
        return EXIT_ERROR
    _emit_json({"records": records, "count": len(records)})
    return EXIT_OK


def cmd_correct(args: argparse.Namespace) -> int:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    defs = record_defs(contract)
    try:
        old = store.read_record(args.type, args.id)
    except StoreError as exc:
        _emit_json({"error": "not_found", "message": str(exc)})
        return EXIT_ERROR
    record_def = defs[old["record_type"]]
    if record_def.get("correction") != "successor_record":
        _emit_json(
            {
                "error": "not_correctable",
                "message": f"{old['record_type']} does not use successor-record correction",
            }
        )
        return EXIT_VALIDATION
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
    )
    known_ids = {item["id"] for item in store.iter_records()} | {new_id}
    try:
        validate_record(contract, new_record, known_ids)
    except ValidationError as exc:
        _emit_json({"error": "validation", "message": str(exc)})
        return EXIT_VALIDATION
    stored = _persist_new(store, record_def, new_record)
    _emit_json({"status": "corrected", "old": old["id"], "new": stored})
    return EXIT_OK


def cmd_contradict(args: argparse.Namespace) -> int:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    defs = record_defs(contract)
    try:
        old = store.read_record(args.type, args.id)
    except StoreError as exc:
        _emit_json({"error": "not_found", "message": str(exc)})
        return EXIT_ERROR
    record_def = defs[old["record_type"]]
    if record_def.get("contradiction") != "separate_record":
        _emit_json(
            {
                "error": "not_contradictable",
                "message": f"{old['record_type']} does not use separate-record contradiction",
            }
        )
        return EXIT_VALIDATION
    payload = _load_payload(args.payload)
    subject = args.subject or payload.get("subject")
    if not subject:
        _emit_json({"error": "missing_subject"})
        return EXIT_ERROR
    new_id = store.new_id()
    new_record = _base_record(
        old["record_type"],
        record_def,
        subject=subject,
        stewardship=args.steward or old.get("stewardship") or "agent",
        payload=payload,
        record_id=new_id,
    )
    updated = dict(old)
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
            _emit_json({"error": "invalid_transition", "message": str(exc)})
            return EXIT_TRANSITION
        updated["lifecycle_state"] = args.transition
        if requires_dimension(record_def, "epistemic_status"):
            updated["epistemic_status"] = args.transition
    known_ids = {item["id"] for item in store.iter_records()} | {new_id}
    try:
        validate_record(contract, new_record, known_ids)
        validate_record(contract, updated, known_ids)
    except ValidationError as exc:
        _emit_json({"error": "validation", "message": str(exc)})
        return EXIT_VALIDATION
    stored = _persist_new(store, record_def, new_record)
    archive_prior = old if requires_history(record_def) else None
    try:
        store.write_record(
            updated,
            expected_revision=args.expected_revision,
            archive_prior=archive_prior,
        )
    except StaleWriteError as exc:
        _emit_json({"error": "stale_write", "message": str(exc)})
        return EXIT_STALE
    _emit_json({"status": "contradicted", "old": updated["id"], "new": stored})
    return EXIT_OK


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
    by_type: dict[str, dict[str, Any]] = {}
    for part in parts:
        if not isinstance(part, dict) or "type" not in part:
            _emit_json({"error": "invalid_records", "message": "each record needs type"})
            return EXIT_ERROR
        by_type[part["type"]] = part
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
    created: dict[str, dict[str, Any]] = {}
    for record_type in _capture_create_order(bundle):
        part = by_type[record_type]
        payload = part.get("payload") or {}
        subject = part.get("subject") or payload.get("subject")
        if not subject:
            _emit_json({"error": "missing_subject", "type": record_type})
            return EXIT_ERROR
        relationships: dict[str, list[str]] = {}
        for link in bundle.get("relationships") or []:
            if link["from"] != record_type:
                continue
            target = created.get(link["to"])
            if target is None:
                _emit_json(
                    {
                        "error": "bundle_order",
                        "message": f"cannot link {record_type} before {link['to']}",
                    }
                )
                return EXIT_ERROR
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
        )
        known_ids = {item["id"] for item in store.iter_records()} | {record_id}
        try:
            validate_record(contract, record, known_ids)
        except ValidationError as exc:
            _emit_json({"error": "validation", "message": str(exc)})
            return EXIT_VALIDATION
        created[record_type] = _persist_new(store, defs[record_type], record)
    _emit_json(
        {
            "status": "captured",
            "bundle": bundle["id"],
            "records": created,
        }
    )
    return EXIT_OK


def cmd_handoff(args: argparse.Namespace) -> int:
    try:
        store, contract = _open_store(args)
    except (ContractBindingError, StoreNotInitializedError, PartialStoreError) as exc:
        return _handle_store_open_error(exc)
    records = list(store.iter_records())
    try:
        markdown = generate_handoff(contract, records)
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
    if args.id:
        try:
            view_by_id(contract, args.id)
            markdown = generate_view(contract, args.id, records)
        except ContractError as exc:
            _emit_json({"error": "view_not_found", "message": str(exc)})
            return EXIT_VALIDATION
        rendered = {args.id: markdown}
    else:
        rendered = generate_all_views(contract, records)
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
    _emit_json({"status": "valid", "records": len(records)})
    return EXIT_OK


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
    views = generate_all_views(contract, records)
    handoff_id = next((view_id for view_id in views if view_id.endswith(":handoff")), None)
    _emit_json(
        {
            "handoff": views.get(handoff_id, "") if handoff_id else "",
            "views": views,
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
    p_create.add_argument("--payload", help="JSON payload object")
    p_create.add_argument(
        "--rel",
        action="append",
        default=[],
        help="Relationship as type:target_id (repeatable)",
    )
    p_create.set_defaults(func=cmd_create)

    p_update = sub.add_parser("update", help="Transition or mutate an existing record")
    p_update.add_argument("--type", required=True)
    p_update.add_argument("--id", required=True)
    p_update.add_argument("--transition", required=True, help="Target lifecycle state")
    p_update.add_argument("--expected-revision", required=True)
    p_update.add_argument("--payload", help="JSON payload updates")
    p_update.add_argument(
        "--rel",
        action="append",
        default=[],
        help="Relationship as type:target_id (repeatable)",
    )
    p_update.set_defaults(func=cmd_update)

    p_sup = sub.add_parser("supersede", help="Supersede with a new record id")
    p_sup.add_argument("--type", required=True)
    p_sup.add_argument("--id", required=True)
    p_sup.add_argument("--expected-revision", required=True)
    p_sup.add_argument("--payload", help="JSON payload for successor")
    p_sup.set_defaults(func=cmd_supersede)

    p_correct = sub.add_parser("correct", help="Append a correcting successor; original stays recorded")
    p_correct.add_argument("--type", required=True)
    p_correct.add_argument("--id", required=True)
    p_correct.add_argument("--payload", help="JSON payload overrides for successor")
    p_correct.add_argument("--subject", help="Successor subject (defaults to original)")
    p_correct.add_argument("--steward", help="Steward identifier")
    p_correct.set_defaults(func=cmd_correct)

    p_contradict = sub.add_parser(
        "contradict", help="Create a contradicting record and link the original"
    )
    p_contradict.add_argument("--type", required=True)
    p_contradict.add_argument("--id", required=True)
    p_contradict.add_argument("--expected-revision", required=True)
    p_contradict.add_argument("--subject", help="Subject of the contradicting record")
    p_contradict.add_argument("--payload", required=True, help="JSON payload for the new record")
    p_contradict.add_argument("--transition", help="Optional lifecycle transition on the original")
    p_contradict.add_argument("--steward", help="Steward identifier")
    p_contradict.set_defaults(func=cmd_contradict)

    p_capture = sub.add_parser("capture", help="Capture a bundle of records")
    p_capture.add_argument("--bundle", required=True, help="Qualified bundle id")
    p_capture.add_argument(
        "--records",
        required=True,
        help="JSON list of {type, subject, payload} objects",
    )
    p_capture.set_defaults(func=cmd_capture)

    p_get = sub.add_parser("get", help="Fetch one record")
    p_get.add_argument("--type", required=True)
    p_get.add_argument("--id", required=True)
    p_get.set_defaults(func=cmd_get)

    p_list = sub.add_parser("list", help="List records")
    p_list.add_argument("--type")
    p_list.add_argument("--state")
    p_list.set_defaults(func=cmd_list)

    p_handoff = sub.add_parser("handoff", help="Generate derived handoff markdown")
    p_handoff.add_argument("--out", help="Optional output path under store")
    p_handoff.set_defaults(func=cmd_handoff)

    p_view = sub.add_parser("view", help="Generate a derived view from the contract")
    p_view.add_argument("--id", help="Qualified view id; omit to render all")
    p_view.add_argument("--out", help="Optional output path under store")
    p_view.set_defaults(func=cmd_view)

    p_validate = sub.add_parser("validate", help="Validate store against contract")
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
