"""Validate records and store invariants against the resolved contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contract import (
    advertises_corrects,
    advertises_supersedes,
    allowed_transition,
    has_trait,
    is_append_only,
    record_defs,
    requires_dimension,
)
from paths import revision_filename, type_dir_name
from revision import compute_revision


class ValidationError(Exception):
    pass


def _require_fields(record: dict[str, Any], fields: list[str], label: str) -> None:
    missing = [field for field in fields if field not in record]
    if missing:
        raise ValidationError(f"{label}: missing required fields {missing}")


def validate_payload(record_def: dict[str, Any], record: dict[str, Any]) -> None:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise ValidationError(f"{record['id']}: payload must be an object")
    for field in record_def.get("payload", []):
        if field == "subject":
            continue
        if field not in payload:
            raise ValidationError(f"{record['id']}: missing payload field {field!r}")
    if "blocking" in record_def.get("payload", []):
        if not isinstance(payload.get("blocking"), bool):
            raise ValidationError(f"{record['id']}: blocking must be bool")


def validate_relationships(
    record_def: dict[str, Any], record: dict[str, Any], known_ids: set[str]
) -> None:
    allowed = set(record_def.get("relationships", []))
    relationships = record.get("relationships") or {}
    if not isinstance(relationships, dict):
        raise ValidationError(f"{record['id']}: relationships must be an object")
    for rel_type, targets in relationships.items():
        if rel_type not in allowed:
            raise ValidationError(f"{record['id']}: unknown relationship {rel_type!r}")
        if not isinstance(targets, list):
            raise ValidationError(f"{record['id']}: relationship {rel_type} must be a list")
        for target in targets:
            if target not in known_ids:
                raise ValidationError(f"{record['id']}: unknown relationship target {target!r}")


def validate_record(
    contract: dict[str, Any],
    record: dict[str, Any],
    known_ids: set[str] | None = None,
) -> None:
    defs = record_defs(contract)
    record_type = record.get("record_type")
    if record_type not in defs:
        raise ValidationError(f"unknown record type {record_type!r}")
    record_def = defs[record_type]
    required = ["id", "record_type", "subject", "payload", "lifecycle_state", "revision"]
    if requires_dimension(record_def, "stewardship"):
        required.append("stewardship")
    if requires_dimension(record_def, "epistemic_status"):
        required.append("epistemic_status")
    if requires_dimension(record_def, "adoption_or_deontic_status"):
        required.append("adoption_or_deontic_status")
    if requires_dimension(record_def, "time"):
        required.append("time")
    if requires_dimension(record_def, "provenance"):
        required.append("provenance")
    _require_fields(record, required, record["id"])
    if record["lifecycle_state"] not in record_def["lifecycle"]["states"]:
        raise ValidationError(
            f"{record['id']}: invalid lifecycle state {record['lifecycle_state']!r}"
        )
    validate_payload(record_def, record)
    validate_relationships(record_def, record, known_ids or {record["id"]})


def position_key(record: dict[str, Any]) -> tuple[str, str]:
    scope = record.get("payload", {}).get("scope", "")
    return (record.get("subject", ""), scope)


def identity_continues(old: dict[str, Any], new: dict[str, Any]) -> bool:
    if old["subject"] != new["subject"]:
        return False
    old_scope = (old.get("payload") or {}).get("scope")
    new_scope = (new.get("payload") or {}).get("scope")
    if old_scope is not None or new_scope is not None:
        return old_scope == new_scope
    return True


def validate_supersedes_links(records: list[dict[str, Any]], defs: dict[str, dict], errors: list[str]) -> None:
    by_id = {record["id"]: record for record in records}
    for record in records:
        record_def = defs[record["record_type"]]
        allowed = set(record_def.get("relationships", []))
        for rel_type, targets in (record.get("relationships") or {}).items():
            if rel_type not in allowed:
                continue
            for target_id in targets:
                target = by_id.get(target_id)
                if target is None:
                    errors.append(f"{record['id']}: relationship target {target_id} missing")
                    continue
                if rel_type == "supersedes":
                    if target["record_type"] != record["record_type"]:
                        errors.append(
                            f"{record['id']}: supersedes target {target_id} has different type"
                        )
                    elif target["lifecycle_state"] != "superseded":
                        errors.append(
                            f"{record['id']}: supersedes target {target_id} not superseded"
                        )
                    elif not identity_continues(target, record):
                        errors.append(
                            f"{record['id']}: supersedes successor breaks identity continuity with {target_id}"
                        )


def validate_orphan_superseded(records: list[dict[str, Any]], defs: dict[str, dict], errors: list[str]) -> None:
    for record in records:
        if record["lifecycle_state"] != "superseded":
            continue
        record_def = defs[record["record_type"]]
        if not advertises_supersedes(record_def):
            continue
        successors = [
            candidate
            for candidate in records
            if candidate["record_type"] == record["record_type"]
            and record["id"] in (candidate.get("relationships") or {}).get("supersedes", [])
        ]
        if len(successors) != 1:
            errors.append(
                f"{record['id']}: superseded record requires exactly one same-type successor, "
                f"found {len(successors)}"
            )
            continue
        if not identity_continues(record, successors[0]):
            errors.append(
                f"{successors[0]['id']}: successor breaks identity continuity with {record['id']}"
            )


def _validate_history_path_layout(path: Path, history_root: Path, snapshot: dict[str, Any], errors: list[str]) -> None:
    try:
        rel = path.relative_to(history_root)
    except ValueError:
        errors.append(f"history snapshot outside history root: {path}")
        return
    parts = rel.parts
    if len(parts) != 3:
        errors.append(f"history snapshot bad layout: {path}")
        return
    type_dir, record_id, filename = parts
    record_type = snapshot.get("record_type")
    snapshot_id = snapshot.get("id")
    revision = snapshot.get("revision")
    if not record_type or not snapshot_id or not revision:
        errors.append(f"history snapshot missing type/id/revision: {path}")
        return
    try:
        expected_type_dir = type_dir_name(record_type)
        expected_filename = revision_filename(revision)
    except ValueError as exc:
        errors.append(f"history snapshot invalid path fields: {path}: {exc}")
        return
    if type_dir != expected_type_dir:
        errors.append(
            f"history snapshot type directory mismatch: {path} expected {expected_type_dir!r}"
        )
    if record_id != snapshot_id:
        errors.append(
            f"history snapshot record id mismatch: {path} expected parent {snapshot_id!r}"
        )
    if filename != expected_filename:
        errors.append(
            f"history snapshot revision filename mismatch: {path} expected {expected_filename!r}"
        )


def validate_history(store_root: Path, records: list[dict[str, Any]], errors: list[str]) -> None:
    history_root = store_root / "history"
    if not history_root.is_dir():
        return
    known_ids = {record["id"] for record in records}
    for path in sorted(history_root.rglob("*.json")):
        try:
            with path.open() as handle:
                snapshot = json.load(handle)
        except json.JSONDecodeError as exc:
            errors.append(f"history malformed JSON {path}: {exc}")
            continue
        if not isinstance(snapshot, dict):
            errors.append(f"history snapshot must be a JSON object: {path}")
            continue
        if snapshot.get("revision") != compute_revision(snapshot):
            errors.append(f"history tamper detected: {path}")
            continue
        _validate_history_path_layout(path, history_root, snapshot, errors)
        record_id = snapshot.get("id")
        record_type = snapshot.get("record_type")
        if record_id not in known_ids:
            errors.append(f"history snapshot {path.name}: unknown record id {record_id!r}")
        if record_type and record_id:
            expected = (
                store_root
                / "records"
                / type_dir_name(record_type)
                / f"{record_id}.json"
            )
            if not expected.is_file():
                errors.append(f"history snapshot {path.name}: no live record for {record_id}")


def load_records_for_validation(store_root: Path, errors: list[str]) -> list[dict[str, Any]]:
    records_dir = store_root / "records"
    if not records_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(records_dir.rglob("*.json")):
        try:
            with path.open() as handle:
                record = json.load(handle)
        except json.JSONDecodeError as exc:
            errors.append(f"record malformed JSON {path}: {exc}")
            continue
        if not isinstance(record, dict):
            errors.append(f"record file must be a JSON object: {path}")
            continue
        if record.get("revision") != compute_revision(record):
            errors.append(f"record revision tamper detected: {path}")
            continue
        records.append(record)
    return records


def validate_store(
    contract: dict[str, Any],
    records: list[dict[str, Any]] | None = None,
    *,
    store_root: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    if records is None and store_root is not None:
        records = load_records_for_validation(store_root, errors)
    records = records or []
    known_ids = {record["id"] for record in records}
    defs = record_defs(contract)

    for record in records:
        try:
            validate_record(contract, record, known_ids)
        except ValidationError as exc:
            errors.append(str(exc))

    active_current: dict[tuple[str, str, str], str] = {}
    for record in records:
        record_def = defs.get(record.get("record_type", ""), {})
        if not has_trait(record_def, "current-claim"):
            continue
        if record.get("lifecycle_state") != "active":
            continue
        key = (record["record_type"],) + position_key(record)
        if key in active_current:
            errors.append(
                f"multiple active {record['record_type']} for subject={key[1]!r} "
                f"scope={key[2]!r}: {active_current[key]} and {record['id']}"
            )
        else:
            active_current[key] = record["id"]

    validate_supersedes_links(records, defs, errors)
    validate_orphan_superseded(records, defs, errors)
    validate_corrects_links(records, defs, errors)
    validate_append_only(records, defs, errors)
    if store_root is not None:
        validate_history(store_root, records, errors)
        validate_append_only_history(store_root, records, defs, errors)
    return errors


def check_transition(record_def: dict[str, Any], src: str, dest: str) -> None:
    if not allowed_transition(record_def, src, dest):
        raise ValidationError(f"invalid transition {src!r} -> {dest!r}")


def reject_supersede_via_update(record_def: dict[str, Any], dest: str) -> None:
    if dest == "superseded" and advertises_supersedes(record_def):
        raise ValidationError("transition to superseded requires the supersede operation")


def reject_append_only_mutation(record_def: dict[str, Any]) -> None:
    if is_append_only(record_def):
        raise ValidationError(
            "append_with_audit records cannot be mutated; create a successor"
        )


def validate_corrects_links(
    records: list[dict[str, Any]], defs: dict[str, dict], errors: list[str]
) -> None:
    by_id = {record["id"]: record for record in records}
    correctors: dict[str, list[str]] = {}
    for record in records:
        record_def = defs.get(record.get("record_type", ""), {})
        if not advertises_corrects(record_def):
            continue
        for target_id in (record.get("relationships") or {}).get("corrects", []):
            target = by_id.get(target_id)
            if target is None:
                errors.append(f"{record['id']}: corrects target {target_id} missing")
                continue
            if target["record_type"] != record["record_type"]:
                errors.append(
                    f"{record['id']}: corrects target {target_id} has different type"
                )
                continue
            if target["lifecycle_state"] != record_def["lifecycle"]["initial"]:
                errors.append(
                    f"{record['id']}: corrects target {target_id} is not in "
                    f"{record_def['lifecycle']['initial']!r} state"
                )
            correctors.setdefault(target_id, []).append(record["id"])
    for target_id, ids in correctors.items():
        if len(ids) != 1:
            errors.append(
                f"{target_id}: occurrence requires exactly one correcting successor, "
                f"found {len(ids)}"
            )


def validate_append_only(
    records: list[dict[str, Any]], defs: dict[str, dict], errors: list[str]
) -> None:
    for record in records:
        record_def = defs.get(record.get("record_type", ""), {})
        if not is_append_only(record_def):
            continue
        if record.get("lifecycle_state") != record_def["lifecycle"]["initial"]:
            errors.append(
                f"{record['id']}: append_with_audit original must stay "
                f"{record_def['lifecycle']['initial']!r}"
            )


def validate_append_only_history(
    store_root: Path,
    records: list[dict[str, Any]],
    defs: dict[str, dict],
    errors: list[str],
) -> None:
    for record in records:
        record_def = defs.get(record.get("record_type", ""), {})
        if not is_append_only(record_def):
            continue
        try:
            path = (
                store_root
                / "history"
                / type_dir_name(record["record_type"])
                / record["id"]
                / revision_filename(record["revision"])
            )
        except ValueError as exc:
            errors.append(f"{record['id']}: invalid append-only history path: {exc}")
            continue
        if not path.is_file():
            errors.append(
                f"{record['id']}: append_with_audit record missing create audit snapshot"
            )
