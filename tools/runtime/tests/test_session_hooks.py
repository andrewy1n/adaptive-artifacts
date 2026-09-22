"""Tests for v0.2 session hook adapters."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
sys.path.insert(0, str(RUNTIME))

from _paths import EXTENSION_ROOT, extension_root  # noqa: E402
from support import RESOLVED, make_git_repo, run_cli, sample_position_payload  # noqa: E402

HOOKS = RUNTIME / "session_hooks.py"


def run_hook(
    fmt: str,
    command: str,
    payload: dict,
    cwd: Path,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(HOOKS), fmt, command],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=merged,
    )


class SessionHooksTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".artifacts"
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))

    def test_start_injects_views_and_writes_files(self):
        r = run_cli("init", store=self.store, contract=RESOLVED, root=self.repo, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stdout)
        created = run_cli(
            "create",
            "--type",
            "project:current-position",
            "--subject",
            "runtime",
            "--payload",
            sample_position_payload(),
            store=self.store,
            root=self.repo,
            cwd=self.repo,
        )
        self.assertEqual(created.returncode, 0, created.stdout)
        hook = run_hook(
            "--cursor",
            "start",
            {"workspace_roots": [str(self.repo)]},
            self.repo,
        )
        self.assertEqual(hook.returncode, 0, hook.stderr + hook.stdout)
        body = json.loads(hook.stdout)
        ctx = body["additional_context"]
        self.assertIn("Derived view", ctx)
        self.assertIn("Views are derived", ctx)
        self.assertTrue((self.store / "views" / "handoff.md").is_file())

    def test_stop_blocks_on_invalid_store(self):
        r = run_cli("init", store=self.store, contract=RESOLVED, root=self.repo, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stdout)
        rec = json.loads(
            run_cli(
                "create",
                "--type",
                "project:current-position",
                "--subject",
                "runtime",
                "--payload",
                sample_position_payload(),
                store=self.store,
                root=self.repo,
                cwd=self.repo,
            ).stdout
        )["record"]
        path = self.store / "records" / "project__current-position" / f"{rec['id']}.json"
        data = json.loads(path.read_text())
        data["payload"]["position"] = "tampered"
        path.write_text(json.dumps(data, indent=2) + "\n")
        hook = run_hook(
            "--cursor",
            "stop",
            {
                "status": "completed",
                "loop_count": 0,
                "workspace_roots": [str(self.repo)],
            },
            self.repo,
        )
        self.assertEqual(hook.returncode, 0, hook.stderr)
        body = json.loads(hook.stdout)
        self.assertIn("followup_message", body)
        self.assertIn("failed", body["followup_message"])

    def test_start_absent_store_still_emits_protocol(self):
        hook = run_hook(
            "--cursor",
            "start",
            {"workspace_roots": [str(self.repo)]},
            self.repo,
        )
        self.assertEqual(hook.returncode, 0, hook.stderr)
        body = json.loads(hook.stdout)
        self.assertIn("Views are derived", body["additional_context"])

    def test_stop_failure_message_includes_stderr_when_json_is_empty(self):
        from session_hooks import stop_failure_message

        result = subprocess.CompletedProcess(
            args=["artifacts.py", "hook-stop"],
            returncode=1,
            stdout="",
            stderr="can't open file '/nonexistent/artifacts.py': [Errno 2] No such file or directory",
        )
        msg = stop_failure_message({}, result)
        self.assertIn("failed", msg)
        self.assertIn("No such file", msg)

    def test_stop_failure_message_has_fallback_when_both_streams_empty(self):
        from session_hooks import stop_failure_message

        result = subprocess.CompletedProcess(
            args=["artifacts.py", "hook-stop"],
            returncode=1,
            stdout="",
            stderr="",
        )
        msg = stop_failure_message({}, result)
        self.assertIn("exited 1 with no output", msg)

    def test_extension_root_ignores_foreign_plugin_root(self):
        foreign = Path(tempfile.mkdtemp(prefix="foreign-plugin-"))
        self.addCleanup(lambda: shutil.rmtree(foreign, ignore_errors=True))
        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": str(foreign)}):
            self.assertEqual(extension_root(), EXTENSION_ROOT)

    def test_extension_root_honors_plugin_that_ships_cli(self):
        plugin = Path(tempfile.mkdtemp(prefix="real-plugin-"))
        self.addCleanup(lambda: shutil.rmtree(plugin, ignore_errors=True))
        cli = plugin / "tools" / "artifacts.py"
        cli.parent.mkdir(parents=True)
        cli.write_text("# plugin copy\n")
        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": str(plugin)}):
            self.assertEqual(extension_root(), plugin)

    def test_stop_ignores_foreign_claude_plugin_root(self):
        r = run_cli("init", store=self.store, contract=RESOLVED, root=self.repo, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stdout)
        foreign = Path(tempfile.mkdtemp(prefix="foreign-plugin-"))
        self.addCleanup(lambda: shutil.rmtree(foreign, ignore_errors=True))
        hook = run_hook(
            "--cursor",
            "stop",
            {
                "status": "completed",
                "loop_count": 0,
                "workspace_roots": [str(self.repo)],
            },
            self.repo,
            env={"CLAUDE_PLUGIN_ROOT": str(foreign)},
        )
        self.assertEqual(hook.returncode, 0, hook.stderr + hook.stdout)
        self.assertEqual(json.loads(hook.stdout), {})

    def test_stop_skips_when_no_store_or_design(self):
        hook = run_hook(
            "--cursor",
            "stop",
            {
                "status": "completed",
                "loop_count": 0,
                "workspace_roots": [str(self.repo)],
            },
            self.repo,
        )
        self.assertEqual(hook.returncode, 0, hook.stderr)
        self.assertEqual(json.loads(hook.stdout), {})


if __name__ == "__main__":
    unittest.main()
