"""Derived Markdown views from resolved view contracts."""

from __future__ import annotations

from typing import Any

from contract import record_matches_selection, view_by_id


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


def _record_line(record: dict[str, Any], role: dict[str, Any]) -> str:
    payload = record.get("payload") or {}
    skip = {"scope", "subject", "blocking", "owner"}
    ordered = [field for field in (role.get("requires_payload") or []) if field not in skip]
    bits = []
    for field in ordered:
        value = payload.get(field)
        if value is None or value == "" or isinstance(value, bool):
            continue
        bits.append(str(value))
    summary = "; ".join(bits)
    owner = payload.get("owner")
    extra = f"owner: {owner}, " if owner else ""
    if summary:
        return f"- **{record['subject']}**: {summary} _({extra}id: {record['id']})_"
    if owner:
        return f"- {record['subject']} _(owner: {owner}, id: {record['id']})_"
    return f"- {record['subject']} _(id: {record['id']})_"


def generate_view(
    contract: dict[str, Any],
    view_id: str,
    records: list[dict[str, Any]],
) -> str:
    view = view_by_id(contract, view_id)
    group_by = (view.get("parameters") or {}).get("group_by") or "subject"
    role_names = [role["name"] for role in view["roles"]]
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for role in view["roles"]:
        for record in _select_records(records, role):
            key = _group_key(record, group_by)
            groups.setdefault(key, {name: [] for name in role_names})
            groups[key][role["name"]].append(record)

    lines = [
        f"# {_title(view_id)}",
        "",
        "> Derived view — not authoritative. Edit underlying records, not this file.",
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
                lines.append(_record_line(record, role))
            lines.append("")
    return "\n".join(lines)


def generate_handoff(contract: dict[str, Any], records: list[dict[str, Any]]) -> str:
    from contract import handoff_view

    return generate_view(contract, handoff_view(contract)["id"], records)


def generate_all_views(contract: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, str]:
    return {
        view["id"]: generate_view(contract, view["id"], records)
        for view in contract.get("views") or []
    }
