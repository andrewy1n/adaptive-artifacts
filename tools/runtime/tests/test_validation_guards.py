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
from record_file import dump_record, prepare_record  # noqa: E402
from revision import with_revision  # noqa: E402
from store import Store  # noqa: E402
from validation import (  # noqa: E402
    ValidationError,
    validate_immutability,
    validate_payload_references,
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


class AuthorizedRecordRewriteTests(unittest.TestCase):
    """A runtime-authored rewrite of a committed record must pass; anything
    else that produces the same `git status M`/`D` must still fail."""

    def setUp(self):
        self.repo = make_git_repo()
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        self.store_root = self.repo / "store"
        self.store = Store(self.store_root)

    def _record(self, **overrides) -> dict:
        base = {
            "id": self.store.new_id(),
            "record_type": "project:thing",
            "subject": "s",
            "payload": {},
            "lifecycle_state": "active",
            "body": "",
        }
        base.update(overrides)
        return with_revision(prepare_record(base))

    def _commit_records(self) -> None:
        # Deliberately commits only records/, not log/ -- the op chain is
        # allowed to be untracked (or absent entirely, like the real
        # 717-record fixture used elsewhere in this suite) without changing
        # what counts as authorized.
        git(self.repo, "add", str(self.store.records_dir))
        result = git(self.repo, "commit", "-qm", "commit store")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_update_written_through_the_store_passes(self):
        record = self._record()
        self.store.create_record(record)
        self._commit_records()
        updated = dict(record)
        updated["payload"] = {"note": "changed"}
        self.store.write_record(updated, expected_revision=record["revision"])
        errors: list[str] = []
        validate_immutability(self.store_root, errors)
        self.assertEqual(errors, [])

    def test_hand_edited_content_with_stale_revision_still_fails(self):
        record = self._record()
        self.store.create_record(record)
        self._commit_records()
        path = self.store.record_path(record["record_type"], record["id"])
        path.write_text(path.read_text().replace('"s"', '"tampered"'))
        errors: list[str] = []
        validate_immutability(self.store_root, errors)
        self.assertEqual(len(errors), 1)
        self.assertIn(record["id"], errors[0])

    def test_deleted_record_still_fails(self):
        record = self._record()
        self.store.create_record(record)
        self._commit_records()
        self.store.record_path(record["record_type"], record["id"]).unlink()
        errors: list[str] = []
        validate_immutability(self.store_root, errors)
        self.assertEqual(len(errors), 1)
        self.assertIn(record["id"], errors[0])

    def test_content_swapped_for_a_different_valid_record_fails(self):
        record = self._record()
        self.store.create_record(record)
        self._commit_records()
        # Self-consistent (correct revision for its own content) but never
        # produced by this record's own op chain -- a forged stand-in, not
        # a runtime rewrite.
        forged = with_revision(
            prepare_record(
                {
                    "id": record["id"],
                    "record_type": record["record_type"],
                    "subject": "hijacked",
                    "payload": {"x": 1},
                    "lifecycle_state": "active",
                    "body": "",
                }
            )
        )
        path = self.store.record_path(record["record_type"], record["id"])
        path.write_text(dump_record(forged))
        errors: list[str] = []
        validate_immutability(self.store_root, errors)
        self.assertEqual(len(errors), 1)
        self.assertIn(record["id"], errors[0])

    def test_legitimate_edit_without_a_surviving_op_chain_still_fails(self):
        # A store whose log/ was never captured (the real 717-record fixture
        # has none) or whose chain got purged gets no benefit of the doubt --
        # same edit as the passing case above, but with the evidence gone.
        record = self._record()
        self.store.create_record(record)
        self._commit_records()
        updated = dict(record)
        updated["payload"] = {"note": "changed"}
        self.store.write_record(updated, expected_revision=record["revision"])
        chain_dir = self.store._chain_dir(record["record_type"], record["id"])
        shutil.rmtree(chain_dir)
        errors: list[str] = []
        validate_immutability(self.store_root, errors)
        self.assertEqual(len(errors), 1)
        self.assertIn(record["id"], errors[0])


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


class PayloadReferenceTests(unittest.TestCase):
    def _defs(self):
        return {
            "project:work-item": {"payload_references": {"phase": "project:phase"}},
            "project:phase": {},
        }

    def _phase(self, phase_id="phase-1", subject="Ingest", lifecycle_state="active"):
        return {
            "id": phase_id,
            "record_type": "project:phase",
            "subject": subject,
            "lifecycle_state": lifecycle_state,
            "payload": {},
        }

    def _work_item(self, phase_value, record_id="wi-1"):
        return {
            "id": record_id,
            "record_type": "project:work-item",
            "subject": "Do the thing",
            "lifecycle_state": "active",
            "payload": {"phase": phase_value},
        }

    def test_reference_matching_existing_subject_passes(self):
        records = [self._phase(), self._work_item("Ingest")]
        errors: list[str] = []
        validate_payload_references(records, self._defs(), errors)
        self.assertEqual(errors, [])

    def test_dangling_reference_fails_and_names_field_value_and_record(self):
        records = [self._phase(), self._work_item("Onboarding")]
        errors: list[str] = []
        validate_payload_references(records, self._defs(), errors)
        self.assertEqual(len(errors), 1)
        self.assertIn("wi-1", errors[0])
        self.assertIn("phase", errors[0])
        self.assertIn("Onboarding", errors[0])

    def test_empty_string_is_treated_as_unset_not_a_violation(self):
        records = [self._phase(), self._work_item("")]
        errors: list[str] = []
        validate_payload_references(records, self._defs(), errors)
        self.assertEqual(errors, [])

    def test_missing_field_entirely_is_not_a_violation(self):
        work_item = self._work_item("Ingest")
        del work_item["payload"]["phase"]
        records = [self._phase(), work_item]
        errors: list[str] = []
        validate_payload_references(records, self._defs(), errors)
        self.assertEqual(errors, [])

    def test_referenced_record_in_non_active_state_still_passes(self):
        # Existence, not currency: a completed/superseded phase is still a
        # valid historical target for a record created while it was live.
        records = [
            self._phase(lifecycle_state="superseded"),
            self._work_item("Ingest"),
        ]
        errors: list[str] = []
        validate_payload_references(records, self._defs(), errors)
        self.assertEqual(errors, [])

    def test_absent_declaration_is_a_no_op(self):
        defs = {"project:work-item": {}, "project:phase": {}}
        records = [self._phase(), self._work_item("Nonexistent")]
        errors: list[str] = []
        validate_payload_references(records, defs, errors)
        self.assertEqual(errors, [])

    def test_no_phase_records_at_all_fails_for_any_non_empty_value(self):
        records = [self._work_item("Ingest")]
        errors: list[str] = []
        validate_payload_references(records, self._defs(), errors)
        self.assertEqual(len(errors), 1)
        self.assertIn("Ingest", errors[0])


if __name__ == "__main__":
    unittest.main()
