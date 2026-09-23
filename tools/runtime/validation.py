"""Validate records and store invariants against the resolved contract."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from record_file import RECORD_GLOB, RECORD_SUFFIX, RecordFileError, load_record
from contract import (
    advertises_corrects,
    advertises_supersedes,
    allowed_transition,
    contract_digest,
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
    optional = set(record_def.get("optional_payload") or [])
    for field in record_def.get("payload", []):
        if field == "subject" or field in optional:
            continue
        if field not in payload:
            raise ValidationError(f"{record['id']}: missing payload field {field!r}")
    if "blocking" in record_def.get("payload", []):
        if not isinstance(payload.get("blocking"), bool):
            raise ValidationError(f"{record['id']}: blocking must be bool")
    for field, allowed in (record_def.get("payload_enum") or {}).items():
        value = payload.get(field, "")
        if value == "":
            continue
        if value not in allowed:
            raise ValidationError(
                f"{record['id']}: payload field {field!r} value {value!r} "
                f"is not one of {allowed}"
            )


_SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")


def _body_sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in (body or "").splitlines():
        match = _SECTION_HEADING_RE.match(line)
        if match:
            current = match.group(1)
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines) for name, lines in sections.items()}


def validate_required_sections(record_def: dict[str, Any], record: dict[str, Any]) -> None:
    required = record_def.get("required_sections") or []
    if not required:
        return
    sections = _body_sections(record.get("body") or "")
    for name in required:
        content = sections.get(name)
        if content is None:
            raise ValidationError(f"{record['id']}: missing required section {name!r}")
        if not content.strip():
            raise ValidationError(f"{record['id']}: required section {name!r} is empty")


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
    validate_required_sections(record_def, record)


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
    for path in sorted(history_root.rglob(RECORD_GLOB)):
        try:
            snapshot = load_record(path.read_text(), path)
        except RecordFileError as exc:
            errors.append(f"history malformed record file {path}: {exc}")
            continue
        if not isinstance(snapshot, dict):
            errors.append(f"history snapshot must be a record object: {path}")
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
                / f"{record_id}{RECORD_SUFFIX}"
            )
            if not expected.is_file():
                errors.append(f"history snapshot {path.name}: no live record for {record_id}")


def _run_git(args: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(args, capture_output=True, text=True)
    except OSError:
        return None


def _git_toplevel(path: Path) -> Path | None:
    result = _run_git(["git", "-C", str(path), "rev-parse", "--show-toplevel"])
    if result is None or result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def _git_head_exists(repo_root: Path) -> bool:
    result = _run_git(["git", "-C", str(repo_root), "rev-parse", "--verify", "-q", "HEAD"])
    return result is not None and result.returncode == 0


def _meta_contract_rel(store_root: Path, repo_root: Path) -> str:
    """Repo-relative path of the contract meta.json pins, or "" when unresolvable."""
    try:
        meta = json.loads((store_root / "meta.json").read_text())
        contract_ref = meta["contract"]
        base = store_root.resolve().parent
        if Path(contract_ref).is_absolute():
            return ""
        return (base / contract_ref).resolve().relative_to(repo_root.resolve()).as_posix()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return ""


def _meta_digest_mismatch(store_root: Path, meta_path: Path) -> str | None:
    """Check whether a modified meta.json is a sanctioned contract re-pin.

    Returns None when the working-tree meta.json's `contract_digest` matches the
    digest of the resolved contract file its own `contract` field points at --
    that is the one legitimate reason meta.json changes (a contract swap during
    development). Any other case (mismatched digest, missing fields, unreadable
    or unparseable contract, malformed meta.json) returns a specific description
    of what's wrong so the violation isn't reported as a generic tamper.
    """
    try:
        text = meta_path.read_text()
    except OSError as exc:
        return f"meta.json unreadable: {exc}"
    try:
        meta = json.loads(text)
    except json.JSONDecodeError as exc:
        return f"meta.json is not valid JSON: {exc}"
    if not isinstance(meta, dict):
        return "meta.json is not a JSON object"
    declared_digest = meta.get("contract_digest")
    contract_ref = meta.get("contract")
    if not isinstance(declared_digest, str) or not declared_digest:
        return "meta.json is missing contract_digest"
    if not isinstance(contract_ref, str) or not contract_ref:
        return "meta.json is missing its contract reference"
    # meta.json's "contract" field is stored relative to store_root's parent (see
    # Store.init). Digest self-consistency only means something if the file it
    # points at is in the tree under review: an absolute or escaping ref lets a
    # writer aim meta.json at attacker-controlled bytes and self-compute a digest
    # that matches, which would pass this check while pointing nowhere auditable.
    base = store_root.resolve().parent
    if Path(contract_ref).is_absolute():
        return f"meta.json contract reference must be relative, got {contract_ref!r}"
    contract_path = (base / contract_ref).resolve()
    if not contract_path.is_relative_to(base):
        return f"meta.json contract reference escapes the project: {contract_ref!r}"
    try:
        contract_text = contract_path.read_text()
    except OSError as exc:
        return f"meta.json points at an unreadable contract ({contract_path}): {exc}"
    try:
        contract_data = json.loads(contract_text)
    except json.JSONDecodeError as exc:
        return f"meta.json points at an unparseable contract ({contract_path}): {exc}"
    if not isinstance(contract_data, dict):
        return f"resolved contract at {contract_path} is not a JSON object"
    actual_digest = contract_digest(contract_data)
    if declared_digest != actual_digest:
        return (
            f"meta.json contract_digest {declared_digest!r} does not match the "
            f"resolved contract on disk at {contract_path} (actual digest {actual_digest!r})"
        )
    return None


def validate_immutability(store_root: Path, errors: list[str]) -> None:
    """Fail on any store path that exists in git HEAD but was changed or removed
    in the working tree. Supersede is the only sanctioned mutation path, and it
    always writes a new record id -- so any in-place change to a path git already
    committed is a violation by construction. New, uncommitted paths are fine.

    History snapshots (`Store.archive_history`/`Store.iter_history`) are
    write-once: it refuses to overwrite an existing snapshot with different
    content and no-ops on a byte-identical rewrite. So they need no
    special-casing here -- a committed snapshot changing at all is already a
    tamper by the same rule as a record file.

    meta.json is the one carve-out: it legitimately changes whenever the
    resolved contract does, since it pins `contract_digest`. A modification is
    let through only when the new digest matches the resolved contract file
    meta.json itself points at -- a deleted meta.json, or one whose digest
    matches nothing real, is still a violation (see `_meta_digest_mismatch`).
    """
    if not store_root.exists():
        return
    repo_root = _git_toplevel(store_root)
    if repo_root is None:
        return
    if not _git_head_exists(repo_root):
        return
    try:
        rel = store_root.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return
    meta_rel = (rel / "meta.json").as_posix()
    result = _run_git(
        [
            "git",
            "-C",
            str(repo_root),
            "diff",
            "--name-status",
            "HEAD",
            "--",
            rel.as_posix(),
        ]
    )
    if result is None or result.returncode != 0:
        return
    for line in result.stdout.splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("A"):
            continue
        offending = parts[1] if len(parts) > 1 else line
        # A contract swap rewrites meta.json and the resolved contract together.
        # Both are sanctioned only while the pair stays self-consistent.
        pinned = {meta_rel, _meta_contract_rel(store_root, repo_root)}
        if offending in pinned and not status.startswith("D"):
            detail = _meta_digest_mismatch(store_root, store_root / "meta.json")
            if detail is None:
                continue
            errors.append(f"immutability violation: {detail}")
            continue
        errors.append(
            f"immutability violation: committed store path modified or deleted "
            f"(git status {status}): {offending}"
        )


def load_records_for_validation(store_root: Path, errors: list[str]) -> list[dict[str, Any]]:
    records_dir = store_root / "records"
    if not records_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(records_dir.rglob("*")):
        # Skipping these quietly would validate an unmigrated store as clean.
        if path.is_file() and path.suffix != RECORD_SUFFIX:
            errors.append(f"unrecognized record file (expected {RECORD_SUFFIX}): {path}")
    for path in sorted(records_dir.rglob(RECORD_GLOB)):
        try:
            record = load_record(path.read_text(), path)
        except RecordFileError as exc:
            errors.append(f"record malformed record file {path}: {exc}")
            continue
        if not isinstance(record, dict):
            errors.append(f"record file must be a record object: {path}")
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
    validate_payload_references(records, defs, errors)
    validate_append_only(records, defs, errors)
    if store_root is not None:
        validate_history(store_root, records, errors)
        validate_append_only_history(store_root, records, defs, errors)
        validate_immutability(store_root, errors)
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


def validate_payload_references(
    records: list[dict[str, Any]], defs: dict[str, dict], errors: list[str]
) -> None:
    """Check payload fields a record definition declares as references to
    another record type's subject.

    A record definition may declare `payload_references`, e.g.
    `{"phase": "project:phase"}`, meaning: for every record of this type, if
    `payload.phase` is set, its value must equal the `subject` of some
    `project:phase` record. This is contract data (threaded through
    resolve.py the same way `required_sections` is), not a hardcoded field
    name, so any record definition can declare it for any payload field.

    This lives here rather than in `validate_record` because checking a
    reference means looking at every *other* record of the target type --
    `validate_record` validates one record in isolation and has no access to
    the rest of the store, so this has to be a whole-store check collected
    by `validate_store`.

    An empty string is treated as "unset", not a violation -- payload fields
    routinely start blank pending assignment elsewhere in this schema, and a
    reference field is no different: unset means "not linked yet", not
    "linked to nothing". The referenced record may be in any lifecycle
    state: this checks existence, not currency, so a phase that has since
    been completed or superseded is still a valid target for a record that
    was created while it was live.
    """
    subjects_by_type: dict[str, set[str]] = {}
    for candidate in records:
        subjects_by_type.setdefault(candidate.get("record_type", ""), set()).add(
            candidate.get("subject", "")
        )
    for record in records:
        record_def = defs.get(record.get("record_type", ""), {})
        references = record_def.get("payload_references") or {}
        if not references:
            continue
        payload = record.get("payload") or {}
        for field, target_type in references.items():
            if field not in payload:
                continue
            value = payload[field]
            if value == "":
                continue
            if value not in subjects_by_type.get(target_type, set()):
                errors.append(
                    f"{record['id']}: payload field {field!r} value {value!r} "
                    f"does not match any {target_type} subject"
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


_STRICT_TERMINAL_SUCCESS_STATES = {"done", "completed"}
FAILING_RESULT_VALUES = {"fail", "failed", "error"}


def _strict_dependency_edges(
    records: list[dict[str, Any]], defs: dict[str, dict], warnings: list[str]
) -> None:
    by_type: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_type.setdefault(record.get("record_type", ""), []).append(record)
    for record_type, items in by_type.items():
        if "depends_on" not in defs.get(record_type, {}).get("relationships", []):
            continue
        if any((item.get("relationships") or {}).get("depends_on") for item in items):
            continue
        warnings.append(
            f"{record_type}: none of {len(items)} records carries a depends_on edge"
        )


def _store_wide_identity_fields(
    records: list[dict[str, Any]], defs: dict[str, dict]
) -> set[str]:
    """Payload field names that hold exactly one value across the whole
    store and are declared on more than one record type.

    A field meant to discriminate between records varies within its own
    type. A field like `effort` or `scope` names something about the store
    itself (which effort it tracks, which workstream it scopes to) rather
    than about any one record -- every type that declares it will carry the
    identical value by construction, and flagging that as "the same value
    across all records" is a false positive no matter how many records set
    it. The signal that separates the two is store-wide, not per-type: a
    field declared on only one type gives no way to tell "shared identity"
    from "this type's field happens to be constant," which is exactly the
    defect this check exists to catch, so single-declarer fields are never
    exempted here.
    """
    declaring_types: dict[str, set[str]] = {}
    for record_type, record_def in defs.items():
        for field in record_def.get("payload", []):
            if field == "subject":
                continue
            declaring_types.setdefault(field, set()).add(record_type)
    values: dict[str, set[Any]] = {}
    for record in records:
        for field, value in (record.get("payload") or {}).items():
            if value == "":
                continue
            values.setdefault(field, set()).add(value)
    return {
        field
        for field, types in declaring_types.items()
        if len(types) >= 2 and len(values.get(field, set())) == 1
    }


# Below this many records, one repeated value is ordinary rather than
# evidence: two decisions naming the same phase is what a phase looks like.
# The defect this check exists to catch spanned 74 records.
_CONSTANT_FIELD_FLOOR = 10


def _strict_constant_payload_fields(
    records: list[dict[str, Any]], defs: dict[str, dict], warnings: list[str]
) -> None:
    exempt = _store_wide_identity_fields(records, defs)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_type.setdefault(record.get("record_type", ""), []).append(record)
    for record_type, items in by_type.items():
        for field in defs.get(record_type, {}).get("payload", []):
            if field == "subject" or field in exempt:
                continue
            # Empty string is this schema's "unset", not a value -- see
            # validate_payload_references for the same convention.
            values = [
                item["payload"][field]
                for item in items
                if item["payload"].get(field, "") != ""
            ]
            if len(values) >= _CONSTANT_FIELD_FLOOR and len(set(values)) == 1:
                warnings.append(
                    f"{record_type}: payload field {field!r} is the same value "
                    f"{values[0]!r} across all {len(values)} records that set it"
                )


def subject_related(parent_subject: str, other_subject: str) -> bool:
    """True when `other_subject` looks derived from `parent_subject`.

    Not a declared relationship -- a subject-prefix convention some importers
    use to link a check/acceptance record back to the item it's about (e.g.
    "<work-item>-ac3"). Heuristic, so false negatives are expected wherever a
    project doesn't follow the convention. Public because `handoff.py` reuses
    this exact heuristic to correlate check-runs back to work-items for the
    status view's criteria tally -- a second, differently-tuned heuristic for
    the same link would eventually disagree with this one.
    """
    if not parent_subject or not other_subject:
        return False
    if other_subject == parent_subject:
        return True
    if not other_subject.startswith(parent_subject):
        return False
    return not other_subject[len(parent_subject)].isalnum()


def _strict_done_with_failing_check(
    records: list[dict[str, Any]], defs: dict[str, dict], warnings: list[str]
) -> None:
    terminal = [
        record
        for record in records
        if record.get("lifecycle_state") in _STRICT_TERMINAL_SUCCESS_STATES
    ]
    if not terminal:
        return
    failing = []
    for record in records:
        record_def = defs.get(record.get("record_type", ""), {})
        if "result" not in record_def.get("payload", []):
            continue
        value = (record.get("payload") or {}).get("result")
        if isinstance(value, str) and value.lower() in FAILING_RESULT_VALUES:
            failing.append(record)
    for record in terminal:
        subject = record.get("subject", "")
        for check in failing:
            if subject_related(subject, check.get("subject", "")):
                warnings.append(
                    f"{record['id']}: lifecycle_state {record['lifecycle_state']!r} "
                    f"but {check['id']} reports result={check['payload']['result']!r}"
                )


def validate_strict(
    records: list[dict[str, Any]], defs: dict[str, dict]
) -> list[str]:
    """Warnings for legal-but-almost-certainly-wrong shapes `validate_store`
    lets through -- opt-in via `validate --strict`, never affects exit status
    of a plain `validate`."""
    warnings: list[str] = []
    _strict_dependency_edges(records, defs, warnings)
    _strict_constant_payload_fields(records, defs, warnings)
    _strict_done_with_failing_check(records, defs, warnings)
    return warnings


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
