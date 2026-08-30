import json
import os
import shutil
import tempfile
import unittest

from fixture import (ENTRY_MD, commit_all, git, make_project, run_lint,
                     write)


class LintTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.art = make_project(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def assert_error(self, out, fragment):
        self.assertIn("ERROR", out)
        self.assertIn(fragment, out)

    def test_clean_tree_passes(self):
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 0, out)
        self.assertIn("0 errors, 0 warnings", out)

    def test_missing_required_field(self):
        write(self.root, ".artifacts/STATE.md", "# State\n\n## Goal\nx.\n")
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 1)
        self.assert_error(out, "missing required field 'Now'")

    def test_budget_overrun(self):
        filler = "\n".join(["line"] * 20)
        write(self.root, ".artifacts/STATE.md",
              f"# State\n\n## Goal\nx.\n\n## Now\ny.\n{filler}\n")
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 1)
        self.assert_error(out, "budget_lines")

    def test_snapshot_file_missing(self):
        os.remove(os.path.join(self.art, "STATE.md"))
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 1)
        self.assert_error(out, "snapshot file missing")

    def test_schema_without_manifest_row(self):
        write(self.root, ".artifacts/schemas/extra.json", json.dumps({
            "name": "extra", "version": 1, "purpose": "t",
            "discipline": "ledger", "layout": "file", "path": "EXTRA.md",
            "fields": []}))
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 1)
        self.assert_error(out, "no Artifacts row for type 'extra'")

    def test_manifest_row_missing_schema(self):
        os.remove(os.path.join(self.art, "schemas", "friction.json"))
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 1)
        self.assert_error(out, "missing schemas/friction.json")

    def test_invalid_schema_json(self):
        write(self.root, ".artifacts/schemas/state.json", "{not json")
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 1)
        self.assert_error(out, "invalid JSON")

    def test_edit_committed_collection_entry(self):
        write(self.root, ".artifacts/failures/001-first-dead-end.md",
              ENTRY_MD.replace("boom", "bang"))
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 1)
        self.assert_error(out, "committed ledger entry modified")

    def test_delete_committed_collection_entry(self):
        os.remove(os.path.join(self.art, "failures",
                               "001-first-dead-end.md"))
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 1)
        self.assert_error(out, "committed ledger entry deleted")

    def test_archive_move_allowed(self):
        src = os.path.join(self.art, "failures", "001-first-dead-end.md")
        dst_dir = os.path.join(self.art, "failures", "archive")
        os.makedirs(dst_dir)
        shutil.move(src, dst_dir)
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 0, out)

    def test_new_uncommitted_entry_allowed(self):
        write(self.root, ".artifacts/failures/002-second.md", ENTRY_MD)
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 0, out)

    def test_id_gap_warns_duplicate_errors(self):
        write(self.root, ".artifacts/failures/004-gap.md", ENTRY_MD)
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 0)
        self.assertIn("id sequence gaps", out)
        write(self.root, ".artifacts/failures/001-duplicate.md", ENTRY_MD)
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 1)
        self.assert_error(out, "duplicate entry id")

    def test_bad_entry_filename(self):
        write(self.root, ".artifacts/failures/notes.md", ENTRY_MD)
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 1)
        self.assert_error(out, "does not match id_format")

    def test_file_ledger_append_only(self):
        write(self.root, ".artifacts/FRICTION.md",
              "# Friction\n\n## #1 — a (2026-08-30)\n\n**Where:** x\n")
        commit_all(self.root, "friction entry")
        # append is fine
        with open(os.path.join(self.art, "FRICTION.md"), "a") as f:
            f.write("\n## #2 — b (2026-08-30)\n\n**Where:** y\n")
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 0, out)
        # editing above the append point is not
        write(self.root, ".artifacts/FRICTION.md",
              "# Friction\n\n## #1 — a (2026-08-30)\n\n**Where:** EDITED\n")
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 1)
        self.assert_error(out, "append point")

    def test_ledger_entry_missing_field(self):
        write(self.root, ".artifacts/failures/002-incomplete.md",
              "# Incomplete (2026-08-30)\n\n**Attempted:** thing\n")
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 1)
        self.assert_error(out, "missing required field 'Observed'")

    def test_unregistered_file_warns(self):
        write(self.root, ".artifacts/NOTES.md", "scratch\n")
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 0)
        self.assertIn("not covered by any schema", out)

    def test_staleness_ignores_artifact_only_commits(self):
        write(self.root, ".artifacts/STATE.md",
              "# State\n\n## Goal\nx.\n\n## Now\nupdated.\n")
        commit_all(self.root, "artifact-only update")
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 0)
        self.assertNotIn("stale", out)

    def test_staleness_warns_on_code_commits(self):
        write(self.root, "code.py", "x = 2\n")
        commit_all(self.root, "code change")
        rc, out = run_lint(self.root)
        self.assertEqual(rc, 0)
        self.assertIn("stale", out)


if __name__ == "__main__":
    unittest.main()
