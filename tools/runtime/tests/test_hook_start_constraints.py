"""Session-start must surface active constraints for the focused effort
alongside the handoff, bounded rather than a full dump -- and must stay
silent (not error) for a design that has no position/constraint roles at
all, since most designs (including this repo's own) don't."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
TOOLS = RUNTIME.parent
REPO_ROOT = TOOLS.parent
CONTRACTS = REPO_ROOT / "design" / "contracts"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(CONTRACTS))
sys.path.insert(0, str(TOOLS))

from resolve import build_source_lock, format_id, load_catalog, resolve_project, write_contract  # noqa: E402
from support import make_git_repo, run_cli  # noqa: E402

import artifacts  # noqa: E402


def _design(catalog: dict) -> dict:
    def record(name: str, pattern: str, payload: list[str]) -> dict:
        return {
            "name": name,
            "pattern": pattern,
            "canonical_for": f"test {name} records",
            "payload": payload,
        }

    def role(name: str, occupant: str, requires_payload: list[str]) -> dict:
        return {
            "name": name,
            "occupant": occupant,
            "requires_payload": requires_payload,
            "selection": {"all": [{"field": "lifecycle_state", "equals": "active"}]},
        }

    return {
        "format": format_id("project-design", catalog["meta"]["project_design_format"]),
        "project": "hook-start-constraints-test",
        "source_lock": build_source_lock(catalog),
        "backend": "git-filesystem",
        "records": [
            record("current-position", "current-status", ["position", "effort"]),
            record("constraint", "definition", ["statement", "effort"]),
        ],
        "views": [
            {
                "name": "handoff",
                "owns_facts": False,
                "roles": [
                    role("position", "current-position", ["position", "effort"]),
                    role("constraint", "constraint", ["statement", "effort"]),
                ],
            }
        ],
    }


class HookStartConstraintsTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        catalog = load_catalog(CONTRACTS)
        design = _design(catalog)
        contract = resolve_project(design, catalog, design_path="fixtures/hook-start-test.json")
        self.contract_path = self.repo / "resolved-contract.json"
        write_contract(contract, self.contract_path)
        self.store = self.repo / ".artifacts"
        r = run_cli(
            "init", store=self.store, contract=self.contract_path, root=self.repo, cwd=self.repo
        )
        self.assertEqual(r.returncode, 0, r.stdout)

    def _create(self, type_: str, subject: str, payload: dict) -> dict:
        result = run_cli(
            "create",
            "--type",
            type_,
            "--subject",
            subject,
            "--payload",
            json.dumps(payload),
            store=self.store,
            contract=self.contract_path,
            root=self.repo,
            cwd=self.repo,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        return json.loads(result.stdout)["record"]

    def _hook_start(self) -> dict:
        result = run_cli(
            "hook-start",
            store=self.store,
            contract=self.contract_path,
            root=self.repo,
            cwd=self.repo,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        return json.loads(result.stdout)

    def test_hook_start_surfaces_active_constraints_for_the_focused_effort(self):
        self._create("project:current-position", "EFFORT-1", {"position": "mid-flight", "effort": "EFFORT-1"})
        self._create("project:constraint", "C1", {"statement": "stay off SSH", "effort": "EFFORT-1"})
        self._create("project:constraint", "C2", {"statement": "unrelated effort", "effort": "EFFORT-2"})
        body = self._hook_start()
        constraints = body["constraints"]
        subjects = [item["subject"] for item in constraints["items"]]
        self.assertIn("C1", subjects)
        self.assertNotIn("C2", subjects)
        self.assertEqual(constraints["total"], 1)

    def test_hook_start_bounds_the_constraint_count(self):
        self._create("project:current-position", "EFFORT-1", {"position": "mid-flight", "effort": "EFFORT-1"})
        for i in range(artifacts.MAX_HOOK_CONSTRAINTS + 3):
            self._create(
                "project:constraint", f"C{i}", {"statement": f"rule {i}", "effort": "EFFORT-1"}
            )
        body = self._hook_start()
        constraints = body["constraints"]
        self.assertEqual(len(constraints["items"]), artifacts.MAX_HOOK_CONSTRAINTS)
        self.assertEqual(constraints["total"], artifacts.MAX_HOOK_CONSTRAINTS + 3)

    def test_hook_start_has_no_constraints_without_an_active_position(self):
        self._create("project:constraint", "C1", {"statement": "orphaned", "effort": "EFFORT-1"})
        body = self._hook_start()
        self.assertEqual(body["constraints"], {"items": [], "total": 0})

    def test_hook_start_on_a_design_without_constraint_or_position_roles_is_silent(self):
        # This repo's own dogfood contract has neither role -- must not error.
        from support import RESOLVED

        repo = make_git_repo()
        self.addCleanup(lambda: shutil.rmtree(repo, ignore_errors=True))
        store = repo / ".artifacts"
        r = run_cli("init", store=store, contract=RESOLVED, root=repo, cwd=repo)
        self.assertEqual(r.returncode, 0, r.stdout)
        result = run_cli(
            "hook-start", store=store, contract=RESOLVED, root=repo, cwd=repo
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        body = json.loads(result.stdout)
        self.assertEqual(body["constraints"], {"items": [], "total": 0})


if __name__ == "__main__":
    unittest.main()
