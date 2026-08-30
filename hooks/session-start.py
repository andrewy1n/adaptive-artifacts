#!/usr/bin/env python3
"""Inject .artifacts/MANIFEST.md into session context.

Usage: session-start.py [--cursor|--claude]
Cursor sessionStart and Claude Code SessionStart emit different JSON shapes.
"""
import json
import os
import sys


def main():
    fmt = sys.argv[1] if len(sys.argv) > 1 else "--cursor"
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    roots = data.get("workspace_roots") or []
    root = roots[0] if roots else data.get("cwd") or os.getcwd()
    manifest = os.path.join(root, ".artifacts", "MANIFEST.md")
    if not os.path.isfile(manifest):
        print("{}")
        return
    with open(manifest) as f:
        content = f.read().strip()
    ctx = (
        "This project uses adaptive artifacts. .artifacts/MANIFEST.md:\n\n"
        + content
        + "\n\nThe project's artifact types are defined in .artifacts/schemas/"
        " (JSON, one per type) — read a schema before writing its artifact."
        " Verify head_commit matches current HEAD before trusting snapshot"
        " artifacts; if stale, diff against reality first. Load artifacts on"
        " relevance only. Append to ledgers at the moment of the event, never"
        " retroactively. At session end rewrite the state artifact, update"
        " the manifest, and ensure lint passes."
    )
    if fmt == "--claude":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": ctx,
            }
        }))
    else:
        print(json.dumps({"additional_context": ctx}))


main()
