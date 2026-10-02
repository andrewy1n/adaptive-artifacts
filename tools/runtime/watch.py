"""Redraw a rendered view in the terminal when its text changes."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, TextIO

from terminal import format_view

CLEAR = "\x1b[2J\x1b[H"


def _frame(render: Callable[[], str], width: int, color: bool) -> tuple[str, bool]:
    try:
        return format_view(render(), width=width, color=color), True
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        return f"Render error: {type(exc).__name__}: {exc}", False


def _header(store_path: str, changed_at: datetime) -> str:
    return f"watch {store_path}  last change {changed_at.strftime('%Y-%m-%d %H:%M:%S')}"


def run_watch(
    render: Callable[[], str],
    *,
    stream: TextIO,
    sleep: Callable[[float], None],
    now: Callable[[], datetime],
    width: Callable[[], int],
    interval: float,
    store_path: str,
    color: bool = False,
    max_iterations: int | None = None,
    once: bool = False,
) -> int:
    if once:
        text, ok = _frame(render, width(), color)
        stream.write(f"{_header(store_path, now())}\n\n{text}\n")
        stream.flush()
        return 0 if ok else 1

    last: tuple[str, int] | None = None
    iteration = 0
    try:
        while True:
            columns = width()
            text, _ = _frame(render, columns, color)
            if (text, columns) != last:
                last = (text, columns)
                stream.write(f"{CLEAR}{_header(store_path, now())}\n\n{text}\n")
                stream.flush()
            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                return 0
            sleep(interval)
    except KeyboardInterrupt:
        return 0
