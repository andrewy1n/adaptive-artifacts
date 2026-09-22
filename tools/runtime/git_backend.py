"""Git repository context checks for the git-filesystem backend."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitContextError(Exception):
    pass


def git_root(start: Path | None = None) -> Path:
    start = start or Path.cwd()
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise GitContextError("git executable not found") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise GitContextError(detail or "not inside a git repository")
    return Path(result.stdout.strip())


def assert_git_context(start: Path | None = None) -> Path:
    return git_root(start)
