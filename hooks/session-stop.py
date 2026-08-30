#!/usr/bin/env python3
"""Session-end artifact gate: run lint against the project's schema
registry and check manifest staleness. Nudges the agent once if either
fails.

Usage: session-stop.py [--cursor|--claude]
Cursor stop hook -> followup_message; Claude Code Stop hook -> decision/block.
"""
import json
import os
import re
import subprocess
import sys

EXT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINT = os.path.join(EXT_ROOT, "tools", "lint.py")
MAX_LINT_LINES = 15


def git_head(root):
    try:
        r = subprocess.run(
            ["git", "-C", root, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def stale_since(root, recorded):
    """Stale only if commits since `recorded` touched files outside
    .artifacts/ — mirrors tools/lint.py semantics."""
    try:
        r = subprocess.run(
            ["git", "-C", root, "log", "--name-only", "--format=",
             f"{recorded}..HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return True
    if r.returncode != 0:
        return True
    return any(l.strip() and not l.startswith(".artifacts/")
               for l in r.stdout.splitlines())


def run_lint(root):
    try:
        r = subprocess.run(
            [sys.executable, LINT, "--root", root],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        return 0, ""
    lines = [l for l in r.stdout.splitlines() if l.startswith("ERROR")]
    shown = lines[:MAX_LINT_LINES]
    if len(lines) > len(shown):
        shown.append(f"... and {len(lines) - len(shown)} more errors")
    return len(lines), "\n".join(shown)


def main():
    fmt = sys.argv[1] if len(sys.argv) > 1 else "--cursor"
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    if fmt == "--claude":
        if data.get("stop_hook_active"):
            return
        root = data.get("cwd") or os.getcwd()
    else:
        if data.get("status") != "completed" or data.get("loop_count", 0) > 0:
            print("{}")
            return
        roots = data.get("workspace_roots") or []
        root = roots[0] if roots else os.getcwd()

    manifest_path = os.path.join(root, ".artifacts", "MANIFEST.md")
    if not os.path.isfile(manifest_path):
        print("{}")
        return

    problems = []

    with open(manifest_path) as f:
        manifest = f.read()
    m = re.search(r"head_commit:\s*([0-9a-fA-F]+)", manifest)
    current = git_head(root)
    recorded = m.group(1) if m else ""
    fresh = recorded and current and (
        current.startswith(recorded) or recorded.startswith(current)
    )
    if current and not fresh and stale_since(root, recorded):
        problems.append(
            "Manifest head_commit (" + (recorded[:12] or "missing")
            + ") does not match HEAD (" + current[:12] + "). If project state"
            " moved this session, rewrite the state artifact per its schema"
            " and update the manifest; otherwise update head_commit only."
        )

    n_errors, lint_out = run_lint(root)
    if n_errors:
        problems.append(
            f"Artifact lint failed ({n_errors} errors) — fix before"
            " finishing:\n" + lint_out
        )

    if not problems:
        print("{}")
        return

    msg = "Session-end artifact check:\n\n" + "\n\n".join(problems)
    if fmt == "--claude":
        print(json.dumps({"decision": "block", "reason": msg}))
    else:
        print(json.dumps({"followup_message": msg}))


main()
