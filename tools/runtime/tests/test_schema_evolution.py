"""Adding a payload field to an existing record type must not invalidate
records written before the field existed, unless the field is declared
required."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
REPO_ROOT = RUNTIME.parent.parent

sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "design" / "contracts"))

from support import git, run_cli  # noqa: E402
from contract import contract_digest  # noqa: E402

SEED = Path("/home/ayin/aa-scratch/seed-artifacts")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _dump_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n")


class SchemaEvolutionTests(unittest.TestCase):
    """Reproduces, against the real 717-record fixture, the failure where
    adding `phase` to `current-position`'s payload invalidates the two
    existing current-position records."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="schema-evolution-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        shutil.copytree(SEED, self.root / ".artifacts")
        git(self.root, "init", "-q")

    def _design_path(self) -> Path:
        return self.root / ".artifacts" / "project-design.json"

    def _resolved_path(self) -> Path:
        return self.root / ".artifacts" / "resolved-contract.json"

    def _add_phase_field(self, *, optional: bool) -> None:
        design = _load_json(self._design_path())
        for record in design["records"]:
            if record["name"] != "current-position":
                continue
            record["payload"].append("phase")
            record.setdefault("payload_references", {})["phase"] = "project:phase"
            if optional:
                record["optional_payload"] = ["phase"]
        _dump_json(self._design_path(), design)

    def _resolve(self):
        result = run_cli("resolve", root=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _repin_contract_digest(self) -> None:
        meta_path = self.root / ".artifacts" / "meta.json"
        meta = _load_json(meta_path)
        meta["contract_digest"] = contract_digest(_load_json(self._resolved_path()))
        _dump_json(meta_path, meta)

    def _validate(self):
        return run_cli("validate", root=self.root)

    def test_baseline_fixture_validates_clean(self):
        self._resolve()
        self._repin_contract_digest()
        result = self._validate()
        payload = json.loads(result.stdout)
        self.assertEqual(payload.get("status"), "valid", result.stdout)

    def test_required_field_addition_invalidates_existing_records(self):
        """Watch-it-fail: the behavior this task exists to fix. Declaring the
        new field required (the old, only behavior) breaks the two existing
        current-position records -- this is the bug, reproduced live."""
        self._add_phase_field(optional=False)
        self._resolve()
        self._repin_contract_digest()
        result = self._validate()
        payload = json.loads(result.stdout)
        self.assertEqual(payload.get("status"), "invalid", result.stdout)
        missing_phase = [
            err for err in payload["errors"] if "missing payload field 'phase'" in err
        ]
        self.assertEqual(len(missing_phase), 2, payload["errors"])

    def test_optional_field_addition_keeps_existing_records_valid(self):
        self._add_phase_field(optional=True)
        self._resolve()
        self._repin_contract_digest()
        result = self._validate()
        payload = json.loads(result.stdout)
        self.assertEqual(payload.get("status"), "valid", result.stdout)
        self.assertEqual(payload.get("records"), 717)

    def test_optional_field_addition_still_catches_a_genuinely_malformed_record(self):
        """The escape hatch is scoped to the declared optional field only --
        a record missing an unrelated required field must still fail."""
        self._add_phase_field(optional=True)
        self._resolve()
        self._repin_contract_digest()
        result = run_cli(
            "create",
            "--type",
            "project:current-position",
            "--subject",
            "a broken record",
            "--payload",
            json.dumps({"position": "somewhere"}),
            root=self.root,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload.get("error"), "validation", result.stdout)
        self.assertIn("scope", payload.get("message", ""))


if __name__ == "__main__":
    unittest.main()
