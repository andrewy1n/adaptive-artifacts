"""`brief <subject>` composes one work-item's linked records into a single
markdown document -- it must not duplicate a generic `view`'s grouping (which
can only bucket by one literal field shared identically across roles, so it
can't put a work-item and its differently-subjected acceptance/finding/
amendment records in the same group)."""

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

from resolve import build_source_lock, format_id, load_catalog, resolve_project, write_contract  # noqa: E402
from support import make_git_repo, run_cli  # noqa: E402


def _brief_design(catalog: dict) -> dict:
    """A minimal design with exactly the six occupant types `brief` composes.
    Every role uses selection {"all": []} -- the selection engine itself is
    exercised by test_selection_operators.py; this fixture only needs to feed
    cmd_brief's own subject/effort scoping layer, not re-prove record_matches_selection.
    work-item uses the current-status pattern (not observation) so the
    freshness test can actually `update` it -- observation is append-only."""

    def record(name: str, payload: list[str], pattern: str = "observation") -> dict:
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
            "selection": {"all": []},
        }

    return {
        "format": format_id("project-design", catalog["meta"]["project_design_format"]),
        "project": "brief-command-test",
        "source_lock": build_source_lock(catalog),
        "backend": "git-filesystem",
        "records": [
            record("work-item", ["title", "effort"], pattern="current-status"),
            record("acceptance", ["criterion"]),
            record("finding", ["claim"]),
            record("constraint", ["statement", "effort"]),
            record("current-position", ["position", "effort"]),
            record("assignment-amendment", ["assignment", "effort"]),
        ],
        "views": [
            {
                "name": "brief",
                "owns_facts": False,
                "roles": [
                    role("work", "work-item", ["title", "effort"]),
                    role("acceptance", "acceptance", ["criterion"]),
                    role("finding", "finding", ["claim"]),
                    role("constraint", "constraint", ["statement", "effort"]),
                    role("position", "current-position", ["position", "effort"]),
                    role("amendment", "assignment-amendment", ["assignment", "effort"]),
                ],
            }
        ],
    }


class BriefCommandTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        catalog = load_catalog(CONTRACTS)
        design = _brief_design(catalog)
        contract = resolve_project(design, catalog, design_path="fixtures/brief-test.json")
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

    def _seed_two_work_items(self):
        self._create(
            "project:work-item", "alpha", {"title": "Alpha work", "effort": "EFFORT-1"}
        )
        self._create(
            "project:work-item", "beta", {"title": "Beta work", "effort": "EFFORT-2"}
        )
        self._create("project:acceptance", "alpha-ac1", {"criterion": "alpha criterion one"})
        self._create("project:acceptance", "beta-ac1", {"criterion": "beta criterion one"})
        self._create("project:finding", "alpha-f1", {"claim": "alpha finding claim"})
        self._create("project:finding", "unrelated-f1", {"claim": "unrelated finding claim"})
        self._create(
            "project:constraint", "C1", {"statement": "alpha constraint", "effort": "EFFORT-1"}
        )
        self._create(
            "project:constraint", "C2", {"statement": "beta constraint", "effort": "EFFORT-2"}
        )
        self._create(
            "project:current-position",
            "EFFORT-1",
            {"position": "mid-flight on alpha", "effort": "EFFORT-1"},
        )
        self._create(
            "project:assignment-amendment",
            "alpha",
            {"assignment": "alpha", "effort": "EFFORT-1"},
        )

    def test_brief_renders_only_records_linked_to_the_named_work_item(self):
        self._seed_two_work_items()
        result = run_cli(
            "brief",
            "alpha",
            store=self.store,
            contract=self.contract_path,
            root=self.repo,
            cwd=self.repo,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        out = result.stdout
        self.assertIn("Brief: alpha", out)
        self.assertIn("Alpha work", out)
        self.assertIn("alpha criterion one", out)
        self.assertIn("alpha finding claim", out)
        self.assertIn("alpha constraint", out)
        self.assertIn("mid-flight on alpha", out)
        self.assertIn("assignment", out)
        # Nothing belonging to the other work-item or its effort leaks in.
        self.assertNotIn("Beta work", out)
        self.assertNotIn("beta criterion one", out)
        self.assertNotIn("beta constraint", out)
        self.assertNotIn("unrelated finding claim", out)

    def test_brief_scopes_constraints_and_position_by_effort_not_subject(self):
        self._seed_two_work_items()
        result = run_cli(
            "brief",
            "alpha",
            store=self.store,
            contract=self.contract_path,
            root=self.repo,
            cwd=self.repo,
        )
        out = result.stdout
        self.assertIn("C1", out)
        self.assertNotIn("C2", out)

    def test_brief_is_composed_fresh_not_stale_after_a_supersede(self):
        self._seed_two_work_items()
        first = run_cli(
            "brief",
            "alpha",
            store=self.store,
            contract=self.contract_path,
            root=self.repo,
            cwd=self.repo,
        ).stdout
        self.assertIn("Alpha work", first)
        current = json.loads(
            run_cli(
                "list",
                "--type",
                "project:work-item",
                "--subject",
                "alpha",
                "--full",
                store=self.store,
                contract=self.contract_path,
                root=self.repo,
                cwd=self.repo,
            ).stdout
        )["records"][0]
        updated = run_cli(
            "update",
            "--type",
            "project:work-item",
            "--id",
            current["id"],
            "--expected-revision",
            current["revision"],
            "--payload",
            json.dumps({"title": "Alpha work, retitled"}),
            store=self.store,
            contract=self.contract_path,
            root=self.repo,
            cwd=self.repo,
        )
        self.assertEqual(updated.returncode, 0, updated.stdout)
        second = run_cli(
            "brief",
            "alpha",
            store=self.store,
            contract=self.contract_path,
            root=self.repo,
            cwd=self.repo,
        ).stdout
        self.assertNotIn("Alpha work\n", second)
        self.assertIn("Alpha work, retitled", second)

    def test_unknown_subject_is_a_machine_readable_not_found_error(self):
        self._seed_two_work_items()
        result = run_cli(
            "brief",
            "no-such-work-item",
            store=self.store,
            contract=self.contract_path,
            root=self.repo,
            cwd=self.repo,
        )
        body = json.loads(result.stdout)
        self.assertEqual(body["error"], "not_found")

    def test_out_writes_the_brief_under_the_store(self):
        self._seed_two_work_items()
        result = run_cli(
            "brief",
            "alpha",
            "--out",
            "views/brief-alpha.md",
            store=self.store,
            contract=self.contract_path,
            root=self.repo,
            cwd=self.repo,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        written = (self.store / "views" / "brief-alpha.md").read_text()
        self.assertIn("Alpha work", written)


if __name__ == "__main__":
    unittest.main()
