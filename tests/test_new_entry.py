import os
import shutil
import tempfile
import unittest

from fixture import make_project, run_new_entry


class NewEntryTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.art = make_project(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_collection_next_id_and_slug(self):
        rc, out, _ = run_new_entry(self.root, "failures",
                                   "ALB Idle Timeout!")
        self.assertEqual(rc, 0)
        self.assertIn("002-alb-idle-timeout.md", out)
        path = out.strip()
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            content = f.read()
        self.assertIn("**Attempted:**", content)
        self.assertIn("**Observed:**", content)
        rc, out, _ = run_new_entry(self.root, "failures", "next one")
        self.assertIn("003-next-one.md", out)

    def test_file_ledger_creates_then_appends(self):
        rc, out, _ = run_new_entry(self.root, "friction", "first")
        self.assertEqual(rc, 0)
        self.assertIn("appended #1", out)
        rc, out, _ = run_new_entry(self.root, "friction", "second")
        self.assertIn("appended #2", out)
        with open(os.path.join(self.art, "FRICTION.md")) as f:
            content = f.read()
        self.assertIn("## #1 — first", content)
        self.assertIn("## #2 — second", content)
        self.assertIn("optional; delete if unused", content)

    def test_snapshot_refused(self):
        rc, _, err = run_new_entry(self.root, "state")
        self.assertNotEqual(rc, 0)
        self.assertIn("snapshot", err)

    def test_unknown_type(self):
        rc, _, err = run_new_entry(self.root, "nonsense")
        self.assertNotEqual(rc, 0)
        self.assertIn("no schema", err)


if __name__ == "__main__":
    unittest.main()
