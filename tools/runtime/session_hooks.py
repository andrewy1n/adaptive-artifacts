"""Session hook adapters for the v0.2 runtime."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from _paths import DEFAULT_STORE_NAME, project_design_path, extension_root
from handoff import view_file_name

PROTOCOL = (
    "This project uses v0.2 artifact records. Views are derived — edit records, "
    "not view files. Capture at the event with `adaptive-artifacts` "
    "(optional `--root <project>`; defaults to cwd). Design-only "
    "(`.artifacts/project-design.json` without a live store) is valid. At "
    "session end regenerate views and run hook-stop; fix validation errors "
    "before finishing."
)

# Session-start context must stay cheap: only the handoff view is injected in
# full. Above this many bytes it gets truncated (see _truncate_handoff) since
# an oversized handoff is what caused the whole injected context to blow past
# the host harness's preview limit and get silently dropped.
MAX_HANDOFF_BYTES = 16384

# Each surfaced constraint statement is cut to this length -- hook-start
# already bounds the count (see artifacts.MAX_HOOK_CONSTRAINTS); this bounds
# the size of each item too, so one verbose statement can't dominate.
MAX_CONSTRAINT_STATEMENT_CHARS = 220


def _render_constraints(constraints: dict) -> list[str]:
    items = constraints.get("items") or []
    if not items:
        return []
    lines = ["", "Active constraints:"]
    for item in items:
        statement = (item.get("statement") or "").strip()
        if len(statement) > MAX_CONSTRAINT_STATEMENT_CHARS:
            statement = statement[:MAX_CONSTRAINT_STATEMENT_CHARS].rstrip() + "…"
        lines.append(f"- **{item.get('subject')}**: {statement}")
    omitted = constraints.get("total", len(items)) - len(items)
    if omitted > 0:
        lines.append(f"(+{omitted} more not shown)")
    return lines


def artifacts_cli() -> Path:
    return extension_root() / "tools" / "artifacts.py"


def _root_from_hook(data: dict, fmt: str) -> Path:
    if fmt == "--claude":
        start = Path(data.get("cwd") or Path.cwd())
    else:
        roots = data.get("workspace_roots") or []
        start = Path(roots[0]) if roots else Path.cwd()
    return start.resolve()


def _run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(artifacts_cli()), "--root", str(root), *args],
        capture_output=True,
        text=True,
        cwd=str(root),
        env=os.environ.copy(),
    )


def _write_views(store: Path, views: dict[str, str]) -> None:
    views_dir = store / "views"
    views_dir.mkdir(parents=True, exist_ok=True)
    for view_id, markdown in views.items():
        (views_dir / view_file_name(view_id)).write_text(markdown)


def _view_file_path(store: Path, view_id: str) -> Path:
    return store / "views" / view_file_name(view_id)


def _truncate_handoff(handoff: str, full_path: Path) -> str:
    encoded = handoff.encode("utf-8")
    if len(encoded) <= MAX_HANDOFF_BYTES:
        return handoff
    head = encoded[:MAX_HANDOFF_BYTES]
    boundary = head.rfind(b"\n")
    if boundary > 0:
        head = head[:boundary]
    text = head.decode("utf-8", errors="ignore").rstrip()
    return (
        f"{text}\n\n"
        f"[... handoff truncated at {MAX_HANDOFF_BYTES} bytes; "
        f"full handoff at {full_path} ...]"
    )


def cmd_start(fmt: str, data: dict) -> dict:
    root = _root_from_hook(data, fmt)
    result = _run_cli(root, "hook-start")
    try:
        body = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        body = {"error": "hook_start_json", "raw": result.stdout}
    if result.returncode != 0:
        ctx = f"v0.2 session-start failed:\n{result.stdout or result.stderr}"
    else:
        store = root / DEFAULT_STORE_NAME
        views = body.get("views") or {}
        if isinstance(views, dict) and views:
            _write_views(store, views)
        parts = [PROTOCOL]
        handoff = body.get("handoff") or ""
        if handoff:
            handoff_id = next(
                (view_id for view_id in views if view_id.endswith(":handoff")),
                None,
            )
            handoff_path = (
                _view_file_path(store, handoff_id)
                if handoff_id
                else store / "views" / "handoff.md"
            )
            parts.extend(["", _truncate_handoff(handoff, handoff_path)])
        constraints = body.get("constraints") or {}
        if isinstance(constraints, dict):
            parts.extend(_render_constraints(constraints))
        if isinstance(views, dict):
            other_paths = [
                str(_view_file_path(store, view_id))
                for view_id in views
                if not view_id.endswith(":handoff")
            ]
            if other_paths:
                parts.extend(["", "Full views on disk: " + ", ".join(other_paths)])
        ctx = "\n".join(parts).strip() + "\n"
    if fmt == "--claude":
        return {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": ctx,
            }
        }
    return {"additional_context": ctx}


def stop_failure_message(body: dict, result: subprocess.CompletedProcess) -> str:
    parts: list[str] = []
    errors = body.get("errors")
    if isinstance(errors, list):
        parts.extend(str(item) for item in errors if item)
    elif errors:
        parts.append(str(errors))
    message = body.get("message")
    if message:
        parts.append(str(message))
    elif body.get("error"):
        parts.append(str(body["error"]))
    stderr = (result.stderr or "").strip()
    if stderr and stderr not in parts:
        parts.append(stderr)
    stdout = (result.stdout or "").strip()
    if not parts and stdout:
        parts.append(stdout)
    if not parts:
        parts.append(f"hook-stop exited {result.returncode} with no output")
    return "Session-end v0.2 store check failed:\n\n" + "\n".join(parts)


def cmd_stop(fmt: str, data: dict) -> dict:
    if fmt == "--claude":
        if data.get("stop_hook_active"):
            return {}
    else:
        if data.get("status") != "completed" or data.get("loop_count", 0) > 0:
            return {}
    root = _root_from_hook(data, fmt)
    store = root / DEFAULT_STORE_NAME
    design = project_design_path(root)
    if not store.exists() and not design.is_file():
        return {}
    result = _run_cli(root, "hook-stop")
    try:
        body = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        body = {"status": "invalid"}
    if result.returncode == 0 and body.get("status") in {"valid", "skipped"}:
        return {}
    msg = stop_failure_message(body, result)
    if fmt == "--claude":
        return {"decision": "block", "reason": msg}
    return {"followup_message": msg}


def main() -> None:
    fmt = sys.argv[1] if len(sys.argv) > 1 else "--cursor"
    command = "start"
    if len(sys.argv) > 2:
        command = sys.argv[2]
    elif "stop" in Path(sys.argv[0]).name:
        command = "stop"
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    if command == "stop":
        out = cmd_stop(fmt, data)
    else:
        out = cmd_start(fmt, data)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
