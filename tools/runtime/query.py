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

WHERE_PREFIX = "payload."
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


def parse_where(raw: Iterable[str] | None) -> list[tuple[str, Any]]:
    """Parse repeatable --where payload.<field>=<value> flags into (field, value) pairs."""
    filters: list[tuple[str, Any]] = []
    for item in raw or []:
        if "=" not in item:
            raise QueryError(f"invalid --where {item!r}; expected payload.<field>=<value>")
        field, _, value = item.partition("=")
        if not field.startswith(WHERE_PREFIX):
            raise QueryError(f"invalid --where {item!r}; only payload.<field> is supported")
        subfield = field[len(WHERE_PREFIX):]
        if not subfield:
            raise QueryError(f"invalid --where {item!r}; missing payload field name")
        filters.append((subfield, _coerce_value(value)))
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


def payload_matches(record: dict[str, Any], filters: list[tuple[str, Any]]) -> bool:
    payload = record.get("payload") or {}
    for field, value in filters:
        actual = payload.get(field, _MISSING)
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


def record_matches(
    record: dict[str, Any],
    *,
    payload_filters: list[tuple[str, Any]] | None = None,
    subject: str | None = None,
    grep: Pattern[str] | None = None,
) -> bool:
    """AND all active predicates, cheapest first.

    Payload/subject checks are dict lookups and string comparisons; the body
    regex only runs on records that already survived those, so a payload-only
    query never pays for a body search, and a query that also filters by
    subject or payload never regex-scans bodies it was always going to reject.
    """
    if not payload_matches(record, payload_filters or []):
        return False
    if not subject_matches(record, subject):
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
    }
    if excerpt:
        summary["body_excerpt"] = truncate(excerpt)
    return summary
