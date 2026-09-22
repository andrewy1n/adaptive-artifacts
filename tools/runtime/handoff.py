"""Derived Markdown views from resolved view contracts."""

from __future__ import annotations

import posixpath
from typing import Any

from contract import canonical_digest, record_matches_selection, view_by_id
from paths import type_dir_name
from record_file import RECORD_SUFFIX
from revision import compute_revision

# Callers that know the real store location (e.g. artifacts.py's cmd_view /
# cmd_handoff / cmd_hook_start) should pass it via store_root. This default
# only covers the standard layout, so out-of-the-box rendering still points
# somewhere real when no caller has been updated to pass one yet.
_DEFAULT_STORE_ROOT = ".artifacts"

# subject is already the bullet label and owner is rendered in the id suffix;
# every other requires_payload field is fair game, including scope/blocking.
_ALWAYS_SUPPRESSED_PAYLOAD_FIELDS = frozenset({"subject", "owner"})


def _group_key(record: dict[str, Any], group_by: str) -> str:
    if group_by == "scope":
        return str(record.get("payload", {}).get("scope", "default"))
    if group_by == "subject":
        return str(record.get("subject", "default"))
    return str(record.get("payload", {}).get(group_by, record.get("subject", "default")))


def _select_records(
    records: list[dict[str, Any]],
    role: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record["record_type"] == role["occupant"]
        and record_matches_selection(record, role["selection"])
    ]


def _title(value: str) -> str:
    return " ".join(part.replace("-", " ").title() for part in value.split(":"))


def _record_relative_path(record: dict[str, Any], store_root: str) -> str:
    """Path to the record's file, relative to the repo root.

    Mirrors Store.record_path's layout (records/<type-dir>/<id>.md) without
    touching the filesystem, so this stays a pure function of the record.
    """
    type_dir = type_dir_name(record["record_type"])
    return posixpath.join(store_root, "records", type_dir, f"{record['id']}{RECORD_SUFFIX}")


def _record_line(
    record: dict[str, Any],
    role: dict[str, Any],
    *,
    store_root: str = _DEFAULT_STORE_ROOT,
) -> str:
    payload = record.get("payload") or {}
    requested = role.get("requires_payload") or []
    ordered = [
        field for field in requested if field not in _ALWAYS_SUPPRESSED_PAYLOAD_FIELDS
    ]
    bits = []
    for field in ordered:
        value = payload.get(field)
        if value is None or value == "":
            continue
        bits.append(str(value))
    summary = "; ".join(bits)
    owner = payload.get("owner")
    extra = f"owner: {owner}, " if owner else ""
    link = f"[{record['id']}]({_record_relative_path(record, store_root)})"
    if summary:
        return f"- **{record['subject']}**: {summary} _({extra}id: {link})_"
    if owner:
        return f"- {record['subject']} _(owner: {owner}, id: {link})_"
    return f"- {record['subject']} _(id: {link})_"


def _store_state_digest(records: list[dict[str, Any]]) -> str:
    """Digest identifying the store state a view's contents were built from.

    Covers exactly the records rendered into a view (any record selected by
    any of its roles): detects an add, remove, or edit (payload, lifecycle
    state, relationships, or body -- revision already covers all of them) to
    any record that could change this view's output. It does not detect
    edits to records this view doesn't select (they can't change this view's
    content) or changes to the view/role definitions themselves (a contract
    change is not a record change). No timestamps or hashes-of-hashes over
    unrelated state, so regenerating an unchanged store is byte-identical.
    """
    revisions = sorted(record.get("revision") or compute_revision(record) for record in records)
    return canonical_digest(revisions)


def generate_view(
    contract: dict[str, Any],
    view_id: str,
    records: list[dict[str, Any]],
    *,
    store_root: str = _DEFAULT_STORE_ROOT,
) -> str:
    view = view_by_id(contract, view_id)
    group_by = (view.get("parameters") or {}).get("group_by") or "subject"
    role_names = [role["name"] for role in view["roles"]]
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    contributing: dict[str, dict[str, Any]] = {}
    for role in view["roles"]:
        for record in _select_records(records, role):
            key = _group_key(record, group_by)
            groups.setdefault(key, {name: [] for name in role_names})
            groups[key][role["name"]].append(record)
            contributing[record["id"]] = record

    lines = [
        f"# {_title(view_id)}",
        "",
        "> Derived view — not authoritative. Edit underlying records, not this file.",
        f"> Store state: {_store_state_digest(list(contributing.values()))}",
        "",
    ]
    if not groups:
        lines.append("_No matching records._")
        lines.append("")
        return "\n".join(lines)

    for group_name in sorted(groups):
        section = groups[group_name]
        lines.append(f"## {group_name}")
        lines.append("")
        for role in view["roles"]:
            items = section.get(role["name"]) or []
            if not items:
                continue
            lines.append(f"### {_title(role['name'])}")
            for record in items:
                lines.append(_record_line(record, role, store_root=store_root))
            lines.append("")
    return "\n".join(lines)


def generate_handoff(
    contract: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    store_root: str = _DEFAULT_STORE_ROOT,
) -> str:
    from contract import handoff_view

    return generate_view(
        contract, handoff_view(contract)["id"], records, store_root=store_root
    )


def generate_all_views(
    contract: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    store_root: str = _DEFAULT_STORE_ROOT,
) -> dict[str, str]:
    return {
        view["id"]: generate_view(contract, view["id"], records, store_root=store_root)
        for view in contract.get("views") or []
    }
