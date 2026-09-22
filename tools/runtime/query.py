"""Freeform record matching for `list` and future read-path callers.

This is deliberately separate from contract.record_matches_selection, which
backs view role selection: that function validates each clause's field
against a single record definition's declared payload/lifecycle schema and
only supports literal equality on `lifecycle_state` or `payload.<field>`,
because a view role is bound to one occupant type the contract already
knows about. A `list` query has no such anchor -- it can span record types,
needs prefix matching on subject and regex search over body prose, and
takes its filter values as raw CLI strings rather than pre-typed JSON
literals from a resolved contract. Reusing record_matches_selection here
would mean either loosening its schema validation (weakening the guarantee
views rely on) or wrapping it so heavily that nothing of it would remain in
use. Building this module alongside it keeps the two matching semantics --
contract-schema-bound selection vs. ad hoc CLI querying -- distinct instead
of half-merged.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Pattern

# derived is read-time only (see derive.py) but a --where clause treats it
# like any other namespaced field -- an agent asking "what's ready" shouldn't
# care that the value isn't stored on disk.
WHERE_NAMESPACES = ("payload", "derived")
DEFAULT_EXCERPT_LIMIT = 160


class QueryError(Exception):
    pass


def _coerce_value(raw: str) -> Any:
    """Best-effort JSON-decode a --where value so `true`/`42`/`"x"` compare
    against their typed payload counterparts; anything else is a literal
    string."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_where(raw: Iterable[str] | None) -> list[tuple[str, str, Any]]:
    """Parse repeatable --where <namespace>.<field>=<value> flags into
    (namespace, field, value) triples. namespace is "payload" or "derived"."""
    filters: list[tuple[str, str, Any]] = []
    for item in raw or []:
        if "=" not in item:
            raise QueryError(
                f"invalid --where {item!r}; expected payload.<field>=<value> or derived.<field>=<value>"
            )
        field, _, value = item.partition("=")
        namespace, sep, subfield = field.partition(".")
        if not sep or namespace not in WHERE_NAMESPACES:
            raise QueryError(
                f"invalid --where {item!r}; only payload.<field> or derived.<field> is supported"
            )
        if not subfield:
            raise QueryError(f"invalid --where {item!r}; missing {namespace} field name")
        filters.append((namespace, subfield, _coerce_value(value)))
    return filters


def compile_grep(pattern: str | None) -> Pattern[str] | None:
    """Compile a --grep pattern once; None means "no body filter"."""
    if pattern is None:
        return None
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise QueryError(f"invalid --grep pattern {pattern!r}: {exc}") from exc


_MISSING = object()


def _same(actual: Any, expected: Any) -> bool:
    # bool is an int subclass, so plain == makes 1 match True. Keep them distinct.
    if isinstance(actual, bool) != isinstance(expected, bool):
        return False
    return actual == expected


def where_matches(record: dict[str, Any], filters: list[tuple[str, str, Any]]) -> bool:
    for namespace, field, value in filters:
        bucket = record.get(namespace) or {}
        actual = bucket.get(field, _MISSING)
        if actual is _MISSING:
            # An absent field is not a null field; =null must not match "never set".
            return False
        if not _same(actual, value):
            return False
    return True


def subject_matches(record: dict[str, Any], subject: str | None) -> bool:
    if subject is None:
        return True
    actual = record.get("subject") or ""
    return actual == subject or actual.startswith(subject)


def body_matches(record: dict[str, Any], grep: Pattern[str] | None) -> bool:
    if grep is None:
        return True
    return grep.search(record.get("body") or "") is not None


def has_inbound(record: dict[str, Any], rel_type: str) -> bool:
    """True if `derived.referenced_by` (see derive.compute_inverse) has at
    least one source recorded under `rel_type`."""
    by_type = (record.get("derived") or {}).get("referenced_by") or {}
    return bool(by_type.get(rel_type))


def within_time_range(record: dict[str, Any], since: str | None, until: str | None) -> bool:
    """`recorded_at` string-compares against ISO-8601 bounds (valid because
    `_now()` is fixed-width UTC). A record with no `recorded_at` (written
    before this field existed) fails any bounded query -- conservative,
    since "unknown when" cannot be asserted to fall inside a range."""
    if since is None and until is None:
        return True
    recorded_at = record.get("recorded_at")
    if not recorded_at:
        return False
    if since is not None and recorded_at < since:
        return False
    if until is not None and recorded_at > until:
        return False
    return True


def order_by_recorded_at(
    records: list[dict[str, Any]], *, reverse: bool = False
) -> list[dict[str, Any]]:
    """Stable sort by `recorded_at`; records missing it (pre-existing,
    backward-compat) sort first regardless of `reverse` -- "unknown when" is
    not "most recent", so `reverse` must only flip ordering among records
    that actually have a timestamp, not push the unknowns to the other end."""
    missing = [record for record in records if not record.get("recorded_at")]
    present = [record for record in records if record.get("recorded_at")]
    present.sort(key=lambda record: record["recorded_at"], reverse=reverse)
    return missing + present


def record_matches(
    record: dict[str, Any],
    *,
    where_filters: list[tuple[str, str, Any]] | None = None,
    subject: str | None = None,
    grep: Pattern[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    has_inbound_types: list[str] | None = None,
) -> bool:
    """AND all active predicates, cheapest first.

    Payload/derived/subject checks are dict lookups and string comparisons;
    the body regex only runs on records that already survived those, so a
    where-only query never pays for a body search, and a query that also
    filters by subject or where never regex-scans bodies it was always going
    to reject.
    """
    if not where_matches(record, where_filters or []):
        return False
    if not subject_matches(record, subject):
        return False
    if not within_time_range(record, since, until):
        return False
    for rel_type in has_inbound_types or []:
        if not has_inbound(record, rel_type):
            return False
    if not body_matches(record, grep):
        return False
    return True


def _first_nonblank_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def matching_line(record: dict[str, Any], grep: Pattern[str]) -> str | None:
    for line in (record.get("body") or "").splitlines():
        if grep.search(line):
            return line.strip()
    return None


def truncate(text: str, limit: int = DEFAULT_EXCERPT_LIMIT) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(limit - 1, 0)].rstrip() + "…"


def summarize(record: dict[str, Any], *, grep: Pattern[str] | None = None) -> dict[str, Any]:
    """Compact, human-scannable projection of a record: no raw body dump.

    Shows a one-line excerpt instead -- the line that matched --grep when one
    was given, else the body's first non-blank line.
    """
    body = record.get("body") or ""
    excerpt = matching_line(record, grep) if grep is not None else None
    if excerpt is None:
        excerpt = _first_nonblank_line(body)
    summary: dict[str, Any] = {
        "id": record.get("id"),
        "record_type": record.get("record_type"),
        "subject": record.get("subject"),
        "lifecycle_state": record.get("lifecycle_state"),
        "revision": record.get("revision"),
        "payload": record.get("payload"),
        "recorded_at": record.get("recorded_at"),
    }
    if "derived" in record:
        summary["derived"] = record["derived"]
    if excerpt:
        summary["body_excerpt"] = truncate(excerpt)
    return summary
