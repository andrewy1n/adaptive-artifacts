"""Derived Markdown views from resolved view contracts."""

from __future__ import annotations

import posixpath
from typing import Any

from contract import canonical_digest, record_matches_selection, view_by_id
from paths import type_dir_name
from record_file import RECORD_SUFFIX
from revision import compute_revision
from validation import FAILING_RESULT_VALUES, subject_related

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


def _field_value(record: dict[str, Any], field: str) -> Any:
    """Resolve a requires_payload entry: `derived.<x>` reads the read-time
    `derived` mapping (see derive.py); anything else reads payload, as before.
    """
    if field.startswith("derived."):
        return (record.get("derived") or {}).get(field[len("derived.") :])
    return (record.get("payload") or {}).get(field)


def _status_bits(
    record: dict[str, Any],
    parameters: dict[str, Any],
    tally_records: list[dict[str, Any]],
) -> list[str]:
    """Extra summary bits a view can ask for beyond requires_payload.

    These read state requires_payload can't reach today (lifecycle_state,
    derive.py's read-time fields) or aren't per-record at all (a pass/fail
    tally over a correlated record type). The check-run<->work-item link
    reuses validation.subject_related -- the same subject-prefix heuristic
    strict mode's done-with-a-failing-check warning already relies on --
    rather than growing a second, differently-tuned version of the same link.
    """
    bits = []
    if parameters.get("show_lifecycle_state"):
        bits.append(f"state: {record.get('lifecycle_state')}")
    for field in parameters.get("show_derived") or []:
        value = (record.get("derived") or {}).get(field)
        if value is not None:
            bits.append(f"{field}: {value}")
    if parameters.get("tally_source_type"):
        result_field = parameters.get("tally_result_field") or "result"
        subject = record.get("subject", "")
        passed = failed = 0
        for candidate in tally_records:
            if not subject_related(subject, candidate.get("subject", "")):
                continue
            value = (candidate.get("payload") or {}).get(result_field)
            if not isinstance(value, str) or not value:
                continue
            if value.lower() in FAILING_RESULT_VALUES:
                failed += 1
            else:
                passed += 1
        bits.append(f"criteria: {passed} pass / {failed} fail")
    return bits


def _tally_source_records(
    parameters: dict[str, Any], records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Records feeding a view's tally, selected by type alone.

    Shared by generate_view and live_view_state_digest so a check-run edit
    marks the view stale exactly when it would change the rendered tally --
    the same reason _group_and_collect/_digest_inputs are already shared.
    """
    tally_type = parameters.get("tally_source_type")
    if not tally_type:
        return []
    return [record for record in records if record["record_type"] == tally_type]


def _record_line(
    record: dict[str, Any],
    role: dict[str, Any],
    *,
    store_root: str = _DEFAULT_STORE_ROOT,
    extra_bits: list[str] | None = None,
    label_fields: bool = False,
) -> str:
    payload = record.get("payload") or {}
    requested = role.get("requires_payload") or []
    ordered = [
        field for field in requested if field not in _ALWAYS_SUPPRESSED_PAYLOAD_FIELDS
    ]
    bits = []
    for field in ordered:
        value = _field_value(record, field)
        if value is None or value == "":
            continue
        bits.append(f"{field}: {value}" if label_fields else str(value))
    bits.extend(extra_bits or [])
    summary = "; ".join(bits)
    # owner renders in its own slot rather than the summary, but still only when
    # the role asked for it -- the allowlist has no exceptions.
    owner = payload.get("owner") if "owner" in requested else None
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


def _digest_inputs(
    contributing: dict[str, dict[str, Any]],
    groups: dict[str, Any],
    order_field: str | None,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Records whose state can change this view's output.

    Under order_by that includes the grouping records supplying the ordinals,
    which no role selects but which decide the order groups render in.
    """
    inputs = dict(contributing)
    if order_field:
        for record in records:
            if record.get("subject") in groups:
                inputs.setdefault(record["id"], record)
    return list(inputs.values())


def _group_ordinal(
    group_name: str, order_field: str, records: list[dict[str, Any]]
) -> int | None:
    """Look up the ordering value for a group from its grouping record.

    The "grouping record" is the record whose `subject` equals the group
    key (e.g. a phase record, when grouping work-items by `payload.phase`).
    It need not be a record any role in this view selects -- it's found by
    scanning the full record set handed to `generate_view`. Candidates are
    tried in id order so a duplicate subject still resolves deterministically.
    Only a plain `int` counts as an orderable value (bool is excluded even
    though it's a Python int subclass); anything else means "not orderable".
    """
    candidates = sorted(
        (record for record in records if record.get("subject") == group_name),
        key=lambda record: record.get("id", ""),
    )
    for candidate in candidates:
        value = (candidate.get("payload") or {}).get(order_field)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _group_sort_key(
    order_field: str | None, records: list[dict[str, Any]]
) -> Any:
    """Sort key: ordinal-ordered groups first (by ordinal, then name to break
    ties), then groups with no declared order_by or no orderable value,
    alphabetically. When order_field is None this reduces to the previous
    plain alphabetical sort, so unchanged views render byte-identical.
    """

    def key(group_name: str) -> tuple[int, Any]:
        if order_field:
            ordinal = _group_ordinal(group_name, order_field, records)
            if ordinal is not None:
                return (0, (ordinal, group_name))
        return (1, (group_name,))

    return key


def _group_and_collect(
    view: dict[str, Any],
    group_by: str,
    records: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], dict[str, dict[str, Any]]]:
    role_names = [role["name"] for role in view["roles"]]
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    contributing: dict[str, dict[str, Any]] = {}
    for role in view["roles"]:
        for record in _select_records(records, role):
            key = _group_key(record, group_by)
            groups.setdefault(key, {name: [] for name in role_names})
            groups[key][role["name"]].append(record)
            contributing[record["id"]] = record
    return groups, contributing


def live_view_state_digest(
    contract: dict[str, Any], view_id: str, records: list[dict[str, Any]]
) -> str:
    """The digest a fresh render of `view_id` would embed right now.

    Shares `_group_and_collect`/`_digest_inputs` with `generate_view` so the
    two can never disagree about which records feed the digest.
    """
    view = view_by_id(contract, view_id)
    parameters = view.get("parameters") or {}
    group_by = parameters.get("group_by") or "subject"
    order_field = parameters.get("order_by")
    groups, contributing = _group_and_collect(view, group_by, records)
    for record in _tally_source_records(parameters, records):
        contributing.setdefault(record["id"], record)
    return _store_state_digest(_digest_inputs(contributing, groups, order_field, records))


_EMBEDDED_STATE_PREFIX = "> Store state: "


def embedded_view_state_digest(rendered: str) -> str | None:
    """The `Store state: sha256:...` digest already written into a rendered
    view, or None if the line is missing (e.g. hand-edited or truncated)."""
    for line in rendered.splitlines():
        if line.startswith(_EMBEDDED_STATE_PREFIX):
            return line[len(_EMBEDDED_STATE_PREFIX) :].strip()
    return None


def view_is_stale(
    contract: dict[str, Any],
    view_id: str,
    records: list[dict[str, Any]],
    rendered: str,
) -> bool:
    """True when `rendered` no longer reflects the store's live state --
    either it embeds no digest at all, or that digest no longer matches."""
    embedded = embedded_view_state_digest(rendered)
    if embedded is None:
        return True
    return embedded != live_view_state_digest(contract, view_id, records)


def generate_view(
    contract: dict[str, Any],
    view_id: str,
    records: list[dict[str, Any]],
    *,
    store_root: str = _DEFAULT_STORE_ROOT,
) -> str:
    view = view_by_id(contract, view_id)
    parameters = view.get("parameters") or {}
    group_by = parameters.get("group_by") or "subject"
    order_field = parameters.get("order_by")
    groups, contributing = _group_and_collect(view, group_by, records)
    tally_records = _tally_source_records(parameters, records)
    for record in tally_records:
        contributing.setdefault(record["id"], record)

    lines = [
        f"# {_title(view_id)}",
        "",
        "> Derived view — not authoritative. Edit underlying records, not this file.",
        f"> Store state: {_store_state_digest(_digest_inputs(contributing, groups, order_field, records))}",
        "",
    ]
    if not groups:
        lines.append("_No matching records._")
        lines.append("")
        return "\n".join(lines)

    for group_name in sorted(groups, key=_group_sort_key(order_field, records)):
        section = groups[group_name]
        lines.append(f"## {group_name}")
        lines.append("")
        for role in view["roles"]:
            # Subject first: ids are random uuids, so id-order is stable but unreadable.
            items = sorted(
                section.get(role["name"]) or [],
                key=lambda r: (r.get("subject", ""), r.get("id", "")),
            )
            if not items:
                continue
            lines.append(f"### {_title(role['name'])}")
            for record in items:
                extra_bits = _status_bits(record, parameters, tally_records)
                lines.append(
                    _record_line(
                        record,
                        role,
                        store_root=store_root,
                        extra_bits=extra_bits,
                        label_fields=bool(parameters.get("label_fields")),
                    )
                )
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


def view_file_name(view_id: str) -> str:
    """Filename a view is written under on disk -- shared by the write side
    (session_hooks._write_views) and the read side (hook-stop's staleness
    check) so the two can't drift apart."""
    return view_id.split(":")[-1] + ".md"
