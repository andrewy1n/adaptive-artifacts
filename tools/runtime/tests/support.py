"""Test helpers for the artifact runtime."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
TOOLS = RUNTIME.parent
REPO_ROOT = TOOLS.parent
CLI = TOOLS / "artifacts.py"
RESOLVED = REPO_ROOT / ".artifacts" / "resolved-contract.json"
PROJECT_DESIGN = REPO_ROOT / ".artifacts" / "project-design.json"


def run_cli(
    *args: str,
    store: Path | None = None,
    contract: Path | None = None,
    root: Path | None = None,
    cwd: Path | None = None,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(CLI)]
    if root is not None:
        cmd.extend(["--root", str(root)])
    if store is not None:
        cmd.extend(["--store", str(store)])
    if contract is not None:
        cmd.extend(["--contract", str(contract)])
    cmd.extend(args)
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO_ROOT),
        env=merged,
    )


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def make_git_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="continuity-"))
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@test")
    git(root, "config", "user.name", "test")
    git(root, "commit", "--allow-empty", "-qm", "init")
    return root


def load_json(text: str) -> dict:
    return json.loads(text)


def sample_position_payload(**overrides) -> str:
    data = {"position": "building runtime", "scope": "design/runtime"}
    data.update(overrides)
    return json.dumps(data)


def sample_commitment_payload(**overrides) -> str:
    data = {
        "actor": "agent",
        "outcome": "ship vertical slice",
        "owner": "agent",
        "effective_time": "2026-09-04T00:00:00+00:00",
        "scope": "design/runtime",
    }
    data.update(overrides)
    return json.dumps(data)


def sample_question_payload(**overrides) -> str:
    data = {"owner": "agent", "blocking": True, "scope": "design/runtime"}
    data.update(overrides)
    return json.dumps(data)


def sample_goal_payload(**overrides) -> str:
    data = {"goal": "keep agents oriented", "scope": "design/runtime"}
    data.update(overrides)
    return json.dumps(data)


def sample_next_payload(**overrides) -> str:
    data = {"next": "run the dogfood trial", "scope": "design/runtime"}
    data.update(overrides)
    return json.dumps(data)


def sample_observation_payload(**overrides) -> dict:
    data = {
        "source": "vendor-docs",
        "observed_time": "2026-09-04T00:00:00+00:00",
        "environment": "sandbox",
        "what_was_observed": "rate limit on retry",
    }
    data.update(overrides)
    return data


def sample_attempt_payload(**overrides) -> dict:
    data = {
        "attempted_action": "retry without backoff",
        "retry_when": "when vendor documents backoff",
    }
    data.update(overrides)
    return data


def sample_finding_payload(**overrides) -> dict:
    data = {
        "claim": "vendor retries are not idempotent",
        "basis": "sandbox replay 2026-09-04",
        "invalidated_when": "vendor publishes idempotency keys",
    }
    data.update(overrides)
    return data


def sample_investigation_question_payload(**overrides) -> dict:
    data = {
        "motivation": "import path keeps duplicating orders",
        "owner": "agent",
    }
    data.update(overrides)
    return data
