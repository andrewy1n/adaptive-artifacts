"""Foreign-project resolve/init/hook-skip cases for the shipped installer."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import (
    CLI,
    PROJECT_DESIGN,
    REPO_ROOT,
    load_json,
    make_git_repo,
    run_cli,
)


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))

    def test_resolve_init_hook_on_foreign_project(self):
        dest = self.repo / ".artifacts"
        dest.mkdir()
        dest.joinpath("project-design.json").write_text(PROJECT_DESIGN.read_text())
        resolved = dest / "resolved-contract.json"
        r = run_cli("resolve", root=self.repo, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue(resolved.is_file())
        body = load_json(r.stdout)
        self.assertEqual(Path(body["path"]), resolved)

        init = run_cli("init", root=self.repo, cwd=self.repo)
        self.assertEqual(init.returncode, 0, init.stderr + init.stdout)
        meta = json.loads((dest / "meta.json").read_text())
        self.assertEqual(meta["contract"], ".artifacts/resolved-contract.json")

        start = run_cli("hook-start", root=self.repo, cwd=self.repo)
        self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
        self.assertEqual(load_json(start.stdout)["records"], 0)

        stop = run_cli("hook-stop", root=self.repo, cwd=self.repo)
        self.assertEqual(stop.returncode, 0, stop.stderr + stop.stdout)
        self.assertEqual(load_json(stop.stdout)["status"], "valid")

    def test_hook_start_skips_absent_store(self):
        r = run_cli("hook-start", root=self.repo, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        body = load_json(r.stdout)
        self.assertEqual(body["note"], "store not initialized")
        self.assertEqual(body["records"], 0)

    def test_legacy_design_dir_still_resolves(self):
        dest = self.repo / "adaptive-artifacts"
        dest.mkdir()
        dest.joinpath("project-design.json").write_text(PROJECT_DESIGN.read_text())
        self.assertEqual(run_cli("resolve", root=self.repo, cwd=self.repo).returncode, 0)
        self.assertTrue((dest / "resolved-contract.json").is_file())
        self.assertEqual(run_cli("init", root=self.repo, cwd=self.repo).returncode, 0)
        meta = json.loads((self.repo / ".artifacts" / "meta.json").read_text())
        self.assertEqual(meta["contract"], "adaptive-artifacts/resolved-contract.json")
        validate = run_cli("validate", root=self.repo, cwd=self.repo)
        self.assertEqual(validate.returncode, 0, validate.stderr + validate.stdout)
        self.assertEqual(load_json(validate.stdout)["status"], "valid")


class PluginPayloadTests(unittest.TestCase):
    def test_wrapper_lock_prints_source_lock(self):
        wrapper = REPO_ROOT / "bin" / "adaptive-artifacts"
        r = subprocess.run(
            [sys.executable, str(wrapper), "lock"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        body = load_json(r.stdout)
        self.assertIn("catalog_version", body)
        for key in ("catalog", "traits", "backends"):
            self.assertIn(key, body)
            self.assertTrue(str(body[key]).startswith("sha256:"))

    def test_lock_matches_resolve_py(self):
        via_cli = subprocess.run(
            [sys.executable, str(CLI), "lock"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        via_resolve = subprocess.run(
            [sys.executable, str(REPO_ROOT / "design" / "contracts" / "resolve.py"), "lock"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(via_cli.returncode, 0, via_cli.stderr + via_cli.stdout)
        self.assertEqual(via_resolve.returncode, 0, via_resolve.stderr + via_resolve.stdout)
        self.assertEqual(via_cli.stdout, via_resolve.stdout)

    def test_sync_plugin_payload(self):
        dest = Path(tempfile.mkdtemp(prefix="aa-payload-"))
        self.addCleanup(lambda: shutil.rmtree(dest, ignore_errors=True))
        script = REPO_ROOT / "scripts" / "sync-plugin.sh"
        r = subprocess.run(
            ["bash", str(script), str(dest)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue((dest / "bin" / "adaptive-artifacts").is_file())
        self.assertTrue((dest / "tools" / "artifacts.py").is_file())
        self.assertTrue((dest / "tools" / "runtime" / "_paths.py").is_file())
        self.assertTrue((dest / ".cursor-plugin" / "plugin.json").is_file())
        self.assertTrue((dest / ".claude-plugin" / "marketplace.json").is_file())
        self.assertTrue((dest / "hooks" / "hooks-cursor.json").is_file())
        self.assertFalse((dest / ".artifacts").exists())
        self.assertFalse((dest / "tools" / "runtime" / "tests").exists())


if __name__ == "__main__":
    unittest.main()
