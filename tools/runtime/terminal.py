"""Format rendered view markdown as plain ANSI terminal text."""

from __future__ import annotations

import os
import re
import sys
from typing import Mapping, TextIO

BOLD = "\x1b[1m"
RESET = "\x1b[0m"
ELLIPSIS = "…"
EMPTY_STATE = "No matching records."

_BANNER_PREFIXES = ("> Derived view", "> Store state:")
_NO_MATCH_LINE = "_No matching records._"
_ID_SUFFIX = re.compile(r"\s*_\((?:(?P<rest>.*?), )?id: \[[^\]]*\]\([^)]*\)\)_$")
_SUBJECT_BOLD = re.compile(r"^- \*\*(?P<subject>.*?)\*\*")


def color_enabled(
    stream: TextIO | None = None, environ: Mapping[str, str] | None = None
) -> bool:
    stream = sys.stdout if stream is None else stream
    environ = os.environ if environ is None else environ
    if environ.get("NO_COLOR"):
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 0:
        return ""
    return text[: width - 1] + ELLIPSIS


def _clean_record_line(line: str) -> str:
    def _suffix(match: re.Match[str]) -> str:
        rest = match.group("rest")
        return f" ({rest})" if rest else ""

    line = _ID_SUFFIX.sub(_suffix, line)
    return _SUBJECT_BOLD.sub(lambda m: f"- {m.group('subject')}", line)


def format_view(markdown: str, *, width: int, color: bool) -> str:
    lines: list[str] = []
    has_records = False
    for raw in markdown.splitlines():
        if raw.startswith(_BANNER_PREFIXES) or raw.strip() == _NO_MATCH_LINE:
            continue
        if raw.startswith("- "):
            has_records = True
            raw = _clean_record_line(raw)
        if not raw.strip() and (not lines or not lines[-1]):
            continue
        lines.append(raw.rstrip())
    while lines and not lines[-1]:
        lines.pop()

    if not has_records:
        title = [line for line in lines if line.startswith("# ")][:1]
        lines = title + [""] + [EMPTY_STATE] if title else [EMPTY_STATE]

    out = []
    for line in lines:
        text = _truncate(line, width)
        if color and line.startswith("#"):
            text = f"{BOLD}{text}{RESET}"
        out.append(text)
    return "\n".join(out)
