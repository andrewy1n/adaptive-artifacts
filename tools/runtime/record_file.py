"""On-disk record serialization: JSON frontmatter + a Markdown body.

Layout, exactly:
    ---
    <json.dumps(record-without-body, sort_keys=True, indent=2)>
    ---

    <body>

The frontmatter never contains raw newlines inside its JSON strings (json.dumps
escapes them), so the first "\\n---\\n" following the opening fence is always
the closing fence, even when the body itself contains "---" lines.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FENCE = "---"
_CLOSING_FENCE = "\n---\n"

RECORD_SUFFIX = ".md"
RECORD_GLOB = f"*{RECORD_SUFFIX}"


class RecordFileError(ValueError):
    pass


def normalize_body(body: str) -> str:
    """Stable body form used on write and before hashing.

    Strips trailing whitespace per line, drops leading/trailing blank lines,
    and ends with exactly one trailing newline. An empty body stays empty.
    """
    if not body:
        return ""
    lines = [line.rstrip() for line in body.split("\n")]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def prepare_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of record with body normalized, for use before hashing/writing."""
    out = dict(record)
    out["body"] = normalize_body(out.get("body", ""))
    return out


def dump_record(record: dict[str, Any]) -> str:
    """Serialize record (body already normalized) to the on-disk text form."""
    body = record.get("body", "")
    frontmatter = {key: value for key, value in record.items() if key != "body"}
    json_text = json.dumps(frontmatter, sort_keys=True, indent=2)
    return f"{FENCE}\n{json_text}\n{FENCE}\n\n{body}"


def load_record(text: str, path: Path | str) -> dict[str, Any]:
    """Parse the on-disk text form back into a record dict (with a body key)."""
    first_line = text.split("\n", 1)[0] if text else ""
    if first_line != FENCE or not text.startswith(f"{FENCE}\n"):
        raise RecordFileError(f"{path}: expected {FENCE!r} as the first line")
    rest = text[len(FENCE) + 1 :]
    idx = rest.find(_CLOSING_FENCE)
    if idx == -1:
        raise RecordFileError(f"{path}: missing closing {FENCE!r} fence")
    frontmatter_text = rest[:idx]
    remainder = rest[idx + len(_CLOSING_FENCE) :]
    if not remainder.startswith("\n"):
        raise RecordFileError(f"{path}: missing blank line after closing {FENCE!r} fence")
    body = remainder[1:]
    try:
        obj = json.loads(frontmatter_text)
    except json.JSONDecodeError as exc:
        raise RecordFileError(f"{path}: malformed frontmatter JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise RecordFileError(f"{path}: frontmatter must be a JSON object")
    obj["body"] = body
    return obj
