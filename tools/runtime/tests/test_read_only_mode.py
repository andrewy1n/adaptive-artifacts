"""--read-only must refuse every mutating command, not a hand-picked sample,
while leaving every read/validate/view command unaffected."""

from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
TOOLS = RUNTIME.parent
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(TOOLS))

from support import RESOLVED, make_git_repo, run_cli, sample_position_payload  # noqa: E402

import artifacts  # noqa: E402

# Minimal but argparse-valid extra args per mutating command, so parse_args
# never rejects the line before the read-only guard gets a chance to run.
_MUTATING_EXTRA_ARGS = {
    "create": ["--type", "project:current-position"],
    "update": ["--type", "project:current-position", "--id", "x", "--expected-revision", "sha256:dead"],
    "supersede": ["--type", "project:current-position", "--id", "x", "--expected-revision", "sha256:dead"],
    "correct": ["--type", "project:current-position", "--id", "x"],
    "contradict": [
        "--type",
        "project:current-position",
        "--id",
        "x",
        "--expected-revision",
        "sha256:dead",
        "--payload",
        "{}",
    ],
    "capture": ["--bundle", "project:whatever", "--records", "[]"],
    "apply": [],
    "init": [],
}


def _all_commands() -> set[str]:
    parser = artifacts.build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("no subparsers action found in build_parser()")


class ReadOnlyGuardCoversEveryMutatingCommandTests(unittest.TestCase):
    """Enumerate commands from the parser itself, not a hand-picked list --
    a new mutating command that forgets to join MUTATING_COMMANDS must fail
    this test instead of shipping unguarded."""

    def setUp(self):
        self.repo = make_git_repo()
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.repo, ignore_errors=True)
        )

    def test_parser_commands_match_the_declared_mutating_set(self):
        self.assertEqual(_all_commands() - {"resolve"} - artifacts.MUTATING_COMMANDS, {
            "lock",
            "get",
            "list",
            "handoff",
            "view",
            "watch",
            "brief",
            "validate",
            "hook-start",
            "hook-stop",
        })

    def test_every_mutating_command_is_refused_under_the_flag(self):
        for command in sorted(artifacts.MUTATING_COMMANDS):
            with self.subTest(command=command):
                result = run_cli(
                    "--read-only",
                    command,
                    *_MUTATING_EXTRA_ARGS[command],
                    root=self.repo,
                    cwd=self.repo,
                )
                body = json.loads(result.stdout)
                self.assertEqual(body.get("error"), "read_only", result.stdout)
                self.assertEqual(result.returncode, artifacts.EXIT_ERROR)

    def test_every_mutating_command_is_refused_under_the_env_var(self):
        import os
        import subprocess

        for command in sorted(artifacts.MUTATING_COMMANDS):
            with self.subTest(command=command):
                env = os.environ.copy()
                env["ADAPTIVE_ARTIFACTS_READONLY"] = "1"
                result = subprocess.run(
                    [
                        sys.executable,
                        str(TOOLS / "artifacts.py"),
                        "--root",
                        str(self.repo),
                        command,
                        *_MUTATING_EXTRA_ARGS[command],
                    ],
                    capture_output=True,
                    text=True,
                    cwd=str(self.repo),
                    env=env,
                )
                body = json.loads(result.stdout)
                self.assertEqual(body.get("error"), "read_only", result.stdout)

    def test_non_mutating_commands_are_not_refused_by_read_only(self):
        r = run_cli("init", store=self.repo / ".artifacts", contract=RESOLVED, root=self.repo, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stdout)
        for command, extra in [
            ("list", []),
            ("validate", []),
            ("handoff", []),
            ("view", []),
            ("brief", ["no-such-subject"]),
            ("hook-start", []),
        ]:
            with self.subTest(command=command):
                result = run_cli(
                    "--read-only",
                    command,
                    *extra,
                    store=self.repo / ".artifacts",
                    root=self.repo,
                    cwd=self.repo,
                )
                # handoff/view print raw markdown (not JSON) on success --
                # only assert none of them hit the read-only refusal at all.
                self.assertNotIn("read_only", result.stdout)


class ReadOnlyGuardBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".artifacts"
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.repo, ignore_errors=True)
        )

    def test_without_the_flag_the_same_command_succeeds(self):
        result = run_cli(
            "init", store=self.store, contract=RESOLVED, root=self.repo, cwd=self.repo
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(self.store.is_dir())

    def test_read_only_init_never_creates_the_store(self):
        result = run_cli(
            "--read-only",
            "init",
            store=self.store,
            contract=RESOLVED,
            root=self.repo,
            cwd=self.repo,
        )
        body = json.loads(result.stdout)
        self.assertEqual(body["error"], "read_only")
        self.assertFalse(self.store.exists())

    def test_read_only_create_produces_the_standard_cli_error_shape(self):
        result = run_cli(
            "--read-only",
            "create",
            "--type",
            "project:current-position",
            "--payload",
            sample_position_payload(),
            store=self.store,
            root=self.repo,
            cwd=self.repo,
        )
        body = json.loads(result.stdout)
        self.assertEqual(set(body), {"error", "message"})
        self.assertEqual(body["error"], "read_only")
        self.assertIn("create", body["message"])


if __name__ == "__main__":
    unittest.main()
