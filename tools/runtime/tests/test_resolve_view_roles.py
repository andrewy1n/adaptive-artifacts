"""Tests for resolve.py's requires_payload enforcement on view roles."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
TOOLS = RUNTIME.parent
REPO_ROOT = TOOLS.parent
CONTRACTS = REPO_ROOT / "design" / "contracts"
sys.path.insert(0, str(CONTRACTS))

from resolve import (  # noqa: E402
    FIXTURE_DIR,
    ResolveError,
    build_source_lock,
    format_id,
    load_catalog,
    resolve_fixture,
    resolve_project,
)


def _minimal_design(catalog: dict) -> dict:
    return {
        "format": format_id(
            "project-design", catalog["meta"]["project_design_format"]
        ),
        "project": "role-requires-payload-test",
        "source_lock": build_source_lock(catalog),
        "backend": "git-filesystem",
        "records": [
            {
                "name": "thing",
                "pattern": "observation",
                "canonical_for": "test observations",
                "payload": ["what_happened"],
            }
        ],
        "views": [
            {
                "name": "summary",
                "owns_facts": False,
                "roles": [
                    {
                        "name": "obs",
                        "occupant": "thing",
                        "requires_payload": ["what_happened"],
                        "selection": {"all": []},
                    }
                ],
            }
        ],
    }


class ViewRoleRequiresPayloadTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(CONTRACTS)

    def test_missing_requires_payload_fails_with_view_role_and_design(self):
        design = _minimal_design(self.catalog)
        del design["views"][0]["roles"][0]["requires_payload"]
        with self.assertRaises(ResolveError) as ctx:
            resolve_project(design, self.catalog, design_path="fixtures/broken-design.json")
        message = str(ctx.exception)
        self.assertIn("project:summary", message)
        self.assertIn("obs", message)
        self.assertIn("fixtures/broken-design.json", message)

    def test_empty_requires_payload_fails_with_view_role_and_design(self):
        design = _minimal_design(self.catalog)
        design["views"][0]["roles"][0]["requires_payload"] = []
        with self.assertRaises(ResolveError) as ctx:
            resolve_project(design, self.catalog, design_path="fixtures/broken-design.json")
        message = str(ctx.exception)
        self.assertIn("project:summary", message)
        self.assertIn("obs", message)
        self.assertIn("fixtures/broken-design.json", message)

    def test_fully_declared_design_resolves(self):
        design = _minimal_design(self.catalog)
        contract = resolve_project(design, self.catalog, design_path="fixtures/ok-design.json")
        role = contract["views"][0]["roles"][0]
        self.assertEqual(role["requires_payload"], ["what_happened"])

    def test_role_missing_requires_payload_error_uses_project_when_no_path(self):
        design = _minimal_design(self.catalog)
        del design["views"][0]["roles"][0]["requires_payload"]
        with self.assertRaises(ResolveError) as ctx:
            resolve_project(design, self.catalog)
        message = str(ctx.exception)
        self.assertIn("role-requires-payload-test", message)

    def test_each_shipped_fixture_resolves(self):
        fixtures = sorted(FIXTURE_DIR.glob("*.json"))
        self.assertTrue(fixtures, "expected shipped fixtures")
        for path in fixtures:
            with self.subTest(fixture=path.name):
                contract = resolve_fixture(path, copy.deepcopy(self.catalog))
                for view in contract["views"]:
                    for role in view["roles"]:
                        self.assertTrue(
                            role["requires_payload"],
                            f"{path.name}: {view['id']}.{role['name']} "
                            "has empty requires_payload",
                        )


if __name__ == "__main__":
    unittest.main()
