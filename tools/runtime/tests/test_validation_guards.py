"""Tests for the immutability gate and required_sections support in validation.py."""

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

from support import git, make_git_repo  # noqa: E402
from contract import contract_digest  # noqa: E402
from validation import (  # noqa: E402
    ValidationError,
    validate_immutability,
    validate_required_sections,
)


def _write(path: Path, content: str = '{"id": "rec-1"}\n') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _write_json(path: Path, data: dict) -> Path:
    return _write(path, json.dumps(data))


class ImmutabilityGateTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        self.store = self.repo / "store"

    def _commit_record(self) -> Path:
        record = _write(self.store / "records" / "project__thing" / "rec-1.json")
        git(self.repo, "add", "-A")
        result = git(self.repo, "commit", "-qm", "add record")
        self.assertEqual(result.returncode, 0, result.stderr)
        return record

    def test_clean_store_passes(self):
        self._commit_record()
        errors: list[str] = []
        validate_immutability(self.store, errors)
        self.assertEqual(errors, [])

    def test_modifying_committed_record_fails_naming_path(self):
        record = self._commit_record()
        record.write_text('{"id": "rec-1", "tampered": true}\n')
        errors: list[str] = []
        validate_immutability(self.store, errors)
        self.assertEqual(len(errors), 1)
        self.assertIn("rec-1.json", errors[0])

    def test_deleting_committed_record_fails_naming_path(self):
        record = self._commit_record()
        record.unlink()
        errors: list[str] = []
        validate_immutability(self.store, errors)
        self.assertEqual(len(errors), 1)
        self.assertIn("rec-1.json", errors[0])

    def test_adding_new_uncommitted_record_passes(self):
        self._commit_record()
        _write(self.store / "records" / "project__thing" / "rec-2.json")
        errors: list[str] = []
        validate_immutability(self.store, errors)
        self.assertEqual(errors, [])

    def test_reports_every_offending_path_not_just_first(self):
        self._commit_record()
        second = _write(self.store / "records" / "project__thing" / "rec-2.json")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "add second record")
        (self.store / "records" / "project__thing" / "rec-1.json").unlink()
        second.write_text("tampered\n")
        errors: list[str] = []
        validate_immutability(self.store, errors)
        self.assertEqual(len(errors), 2)
        joined = "\n".join(errors)
        self.assertIn("rec-1.json", joined)
        self.assertIn("rec-2.json", joined)

    def test_store_path_absent_from_head_produces_no_findings(self):
        # Store dir exists on disk (git repo has a commit elsewhere) but nothing
        # under it has ever been committed -- first commit not yet made for it.
        _write(self.store / "records" / "project__thing" / "rec-1.json")
        errors: list[str] = []
        validate_immutability(self.store, errors)
        self.assertEqual(errors, [])

    def test_repo_with_no_commits_passes_without_crashing(self):
        root = Path(tempfile.mkdtemp(prefix="immutability-nocommit-"))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        git(root, "init", "-q")
        store = root / "store"
        _write(store / "records" / "project__thing" / "rec-1.json")
        errors: list[str] = []
        validate_immutability(store, errors)
        self.assertEqual(errors, [])

    def test_non_git_directory_handled_without_crashing(self):
        root = Path(tempfile.mkdtemp(prefix="immutability-nongit-"))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        store = _write(root / "store" / "records" / "project__thing" / "rec-1.json").parent
        errors: list[str] = []
        validate_immutability(store, errors)
        self.assertEqual(errors, [])

    def _commit_meta(self, contract_data: dict) -> tuple[Path, Path]:
        # meta.json's "contract" field is relative to the store root's parent,
        # matching Store.init's convention.
        contract_path = _write_json(self.repo / "contract.json", contract_data)
        meta_path = _write_json(
            self.store / "meta.json",
            {
                "store_version": 1,
                "contract": "contract.json",
                "contract_digest": contract_digest(contract_data),
            },
        )
        git(self.repo, "add", "-A")
        result = git(self.repo, "commit", "-qm", "add meta.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        return meta_path, contract_path

    def test_meta_json_repin_matching_on_disk_contract_passes(self):
        meta_path, contract_path = self._commit_meta({"a": 1})
        new_contract = {"a": 2}
        contract_path.write_text(json.dumps(new_contract))
        meta_path.write_text(
            json.dumps(
                {
                    "store_version": 1,
                    "contract": "contract.json",
                    "contract_digest": contract_digest(new_contract),
                }
            )
        )
        errors: list[str] = []
        validate_immutability(self.store, errors)
        self.assertEqual(errors, [])

    def test_meta_json_digest_not_matching_on_disk_contract_fails_specifically(self):
        meta_path, _contract_path = self._commit_meta({"a": 1})
        meta_path.write_text(
            json.dumps(
                {
                    "store_version": 1,
                    "contract": "contract.json",
                    "contract_digest": "sha256:doesnotmatchanything",
                }
            )
        )
        errors: list[str] = []
        validate_immutability(self.store, errors)
        self.assertEqual(len(errors), 1)
        self.assertIn("contract_digest", errors[0])
        self.assertIn("does not match", errors[0])
        self.assertIn("sha256:doesnotmatchanything", errors[0])

    def test_meta_json_deleted_fails(self):
        meta_path, _contract_path = self._commit_meta({"a": 1})
        meta_path.unlink()
        errors: list[str] = []
        validate_immutability(self.store, errors)
        self.assertEqual(len(errors), 1)
        self.assertIn("meta.json", errors[0])

    def test_malformed_meta_json_fails(self):
        meta_path, _contract_path = self._commit_meta({"a": 1})
        meta_path.write_text("not even json")
        errors: list[str] = []
        validate_immutability(self.store, errors)
        self.assertEqual(len(errors), 1)
        self.assertIn("not valid JSON", errors[0])


class RequiredSectionsTests(unittest.TestCase):
    def _record(self, body: str) -> dict:
        return {"id": "rec-1", "body": body}

    def test_no_required_sections_declared_passes_regardless_of_body(self):
        validate_required_sections({}, self._record(""))

    def test_all_sections_present_and_non_empty_passes(self):
        record_def = {"required_sections": ["Evidence", "Consequence", "Follow-up"]}
        body = (
            "## Evidence\n"
            "The retry storm showed up in three logs.\n"
            "## Consequence\n"
            "The queue backed up for an hour.\n"
            "## Follow-up\n"
            "Add backoff.\n"
        )
        validate_required_sections(record_def, self._record(body))

    def test_missing_section_fails(self):
        record_def = {"required_sections": ["Evidence", "Consequence"]}
        body = "## Evidence\nSomething happened.\n"
        with self.assertRaises(ValidationError) as ctx:
            validate_required_sections(record_def, self._record(body))
        self.assertIn("Consequence", str(ctx.exception))

    def test_present_but_empty_section_fails(self):
        record_def = {"required_sections": ["Evidence", "Consequence"]}
        body = "## Evidence\nSomething happened.\n## Consequence\n\n"
        with self.assertRaises(ValidationError) as ctx:
            validate_required_sections(record_def, self._record(body))
        self.assertIn("Consequence", str(ctx.exception))

    def test_missing_body_key_treated_as_empty_and_fails(self):
        record_def = {"required_sections": ["Evidence"]}
        with self.assertRaises(ValidationError):
            validate_required_sections(record_def, {"id": "rec-1"})


class ResolveRequiredSectionsThreadingTests(unittest.TestCase):
    def test_required_sections_survive_compose_record(self):
        from resolve import compose_record, load_catalog

        catalog = load_catalog()
        record = {
            "name": "thing",
            "traits": ["entity", "stewarded", "current-claim"],
            "required_sections": ["Evidence", "Consequence"],
        }
        composed = compose_record(record, "test", catalog["traits"], experimental=False)
        self.assertEqual(composed["required_sections"], ["Evidence", "Consequence"])

    def test_absent_required_sections_key_omitted_from_composed_record(self):
        from resolve import compose_record, load_catalog

        catalog = load_catalog()
        record = {
            "name": "thing",
            "traits": ["entity", "stewarded", "current-claim"],
        }
        composed = compose_record(record, "test", catalog["traits"], experimental=False)
        self.assertNotIn("required_sections", composed)


if __name__ == "__main__":
    unittest.main()
