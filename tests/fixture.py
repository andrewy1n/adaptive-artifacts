"""Shared fixture: build a minimal designed project in a temp dir."""
import json
import os
import subprocess
import sys

EXT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINT = os.path.join(EXT_ROOT, "tools", "lint.py")
NEW_ENTRY = os.path.join(EXT_ROOT, "tools", "new_entry.py")

STATE_SCHEMA = {
    "name": "state", "version": 1, "purpose": "test",
    "discipline": "snapshot", "layout": "file", "path": "STATE.md",
    "budget_lines": 12,
    "fields": [
        {"name": "Goal", "required": True},
        {"name": "Now", "required": True},
        {"name": "Open", "required": False},
    ],
}
FAILURES_SCHEMA = {
    "name": "failures", "version": 1, "purpose": "test",
    "discipline": "ledger", "layout": "collection", "path": "failures",
    "id_format": "NNN-slug",
    "fields": [
        {"name": "Attempted", "required": True},
        {"name": "Observed", "required": True},
    ],
}
FRICTION_SCHEMA = {
    "name": "friction", "version": 1, "purpose": "test",
    "discipline": "ledger", "layout": "file", "path": "FRICTION.md",
    "fields": [
        {"name": "Where", "required": True},
        {"name": "Proposal", "required": False},
    ],
}

STATE_MD = "# State\n\n## Goal\nTest.\n\n## Now\nBuilt.\n"

MANIFEST_TMPL = """# Artifact Manifest
manifest_version: 2
head_commit: {commit}
updated: 2026-08-30

## Artifacts
| Type | Path | Schema | Since |
|---|---|---|---|
| state | STATE.md | schemas/state.json | 2026-08-30 |
| failures | failures/ | schemas/failures.json | 2026-08-30 |
| friction | FRICTION.md | schemas/friction.json | 2026-08-30 |
"""

ENTRY_MD = ("# First dead end (2026-08-30)\n\n"
            "**Attempted:** thing\n\n**Observed:** boom\n")


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args],
                          capture_output=True, text=True, check=False)


def commit_all(root, msg):
    git(root, "add", "-A")
    git(root, "commit", "-qm", msg)
    return git(root, "rev-parse", "HEAD").stdout.strip()


def write(root, rel, content):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def make_project(root, with_entry=True):
    """git repo with valid artifacts, stamped fresh. Returns art dir."""
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    art = os.path.join(root, ".artifacts")
    write(root, ".artifacts/schemas/state.json", json.dumps(STATE_SCHEMA))
    write(root, ".artifacts/schemas/failures.json", json.dumps(FAILURES_SCHEMA))
    write(root, ".artifacts/schemas/friction.json", json.dumps(FRICTION_SCHEMA))
    write(root, ".artifacts/STATE.md", STATE_MD)
    if with_entry:
        write(root, ".artifacts/failures/001-first-dead-end.md", ENTRY_MD)
    write(root, "code.py", "x = 1\n")
    h = commit_all(root, "init")
    write(root, ".artifacts/MANIFEST.md", MANIFEST_TMPL.format(commit=h))
    commit_all(root, "stamp artifacts")
    return art


def run_lint(root):
    r = subprocess.run([sys.executable, LINT, "--root", root],
                       capture_output=True, text=True)
    return r.returncode, r.stdout


def run_new_entry(root, typ, title="untitled"):
    r = subprocess.run(
        [sys.executable, NEW_ENTRY, typ, "--title", title, "--root", root],
        capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr
