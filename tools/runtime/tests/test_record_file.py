"""Tests for the frontmatter+body record file format and the store write lock."""

from __future__ import annotations

import json
import multiprocessing
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
REPO_ROOT = RUNTIME.parent.parent
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(REPO_ROOT))

from support import RESOLVED, load_json, make_git_repo, run_cli  # noqa: E402
from record_file import RecordFileError, dump_record, load_record, normalize_body, prepare_record  # noqa: E402
from revision import compute_revision, with_revision  # noqa: E402
from store import Store, StoreLockError  # noqa: E402


def _sample_record(**overrides) -> dict:
    record = {
        "id": "rec-00000000-0000-4000-8000-000000000001",
        "record_type": "ns:kind",
        "base_kind": "claim",
        "subject": "subject",
        "payload": {"scope": "x"},
        "lifecycle_state": "active",
        "relationships": {},
        "revision": "",
        "body": "",
    }
    record.update(overrides)
    return record


class BodyNormalizationTests(unittest.TestCase):
    def test_empty_stays_empty(self):
        self.assertEqual(normalize_body(""), "")

    def test_strips_trailing_whitespace_per_line(self):
        self.assertEqual(normalize_body("line one  \nline two\t\n"), "line one\nline two\n")

    def test_drops_leading_and_trailing_blank_lines(self):
        self.assertEqual(normalize_body("\n\nline one\nline two\n\n\n"), "line one\nline two\n")

    def test_all_blank_normalizes_to_empty(self):
        self.assertEqual(normalize_body("\n   \n\t\n"), "")


class RecordFileRoundTripTests(unittest.TestCase):
    def test_round_trip_without_body(self):
        record = with_revision(prepare_record(_sample_record()))
        loaded = load_record(dump_record(record), "test-path")
        self.assertEqual(loaded, record)

    def test_round_trip_with_body(self):
        record = with_revision(prepare_record(_sample_record(body="hello world\n")))
        loaded = load_record(dump_record(record), "test-path")
        self.assertEqual(loaded, record)

    def test_body_with_fence_lines_and_code_blocks_does_not_break_parsing(self):
        body = (
            "intro paragraph\n"
            "\n"
            "---\n"
            "\n"
            "```python\n"
            "print('hi')\n"
            "x = {'a': 1}\n"
            "```\n"
            "\n"
            "trailing line with --- inline\n"
        )
        record = with_revision(prepare_record(_sample_record(body=body)))
        text = dump_record(record)
        loaded = load_record(text, "test-path")
        self.assertEqual(loaded["body"], body)
        self.assertEqual(loaded, record)

    def test_exact_file_layout(self):
        record = with_revision(prepare_record(_sample_record(body="a line\n")))
        text = dump_record(record)
        frontmatter = {k: v for k, v in record.items() if k != "body"}
        expected = "---\n" + json.dumps(frontmatter, sort_keys=True, indent=2) + "\n---\n\na line\n"
        self.assertEqual(text, expected)

    def test_malformed_missing_leading_fence(self):
        with self.assertRaises(RecordFileError) as ctx:
            load_record("no fence here\n---\n\nbody\n", "/tmp/bad-a.md")
        self.assertIn("/tmp/bad-a.md", str(ctx.exception))

    def test_malformed_bad_json_frontmatter(self):
        text = "---\n{not valid json\n---\n\nbody\n"
        with self.assertRaises(RecordFileError) as ctx:
            load_record(text, "/tmp/bad-b.md")
        self.assertIn("/tmp/bad-b.md", str(ctx.exception))

    def test_malformed_missing_closing_fence(self):
        text = "---\n{}\nbody without a closing fence\n"
        with self.assertRaises(RecordFileError) as ctx:
            load_record(text, "/tmp/bad-c.md")
        self.assertIn("/tmp/bad-c.md", str(ctx.exception))


class StoreRevisionStabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "store")

    def test_revision_stable_across_write_read_cycle(self):
        record = _sample_record(body="a body line\nwith two lines\n")
        stored = self.store.create_record(record)
        reloaded = self.store.read_record(record["record_type"], record["id"])
        self.assertEqual(reloaded, stored)
        self.assertEqual(reloaded["revision"], compute_revision(reloaded))

    def test_revision_unchanged_by_frontmatter_reformatting(self):
        record = _sample_record(body="unchanged body\n")
        stored = self.store.create_record(record)
        path = self.store.record_path(record["record_type"], record["id"])

        frontmatter = {k: v for k, v in stored.items() if k != "body"}
        reformatted_json = json.dumps(frontmatter, indent=4, sort_keys=False)
        reformatted_text = f"---\n{reformatted_json}\n---\n\n{stored['body']}"
        self.assertNotEqual(reformatted_text, path.read_text())
        path.write_text(reformatted_text)

        reloaded = self.store.read_record(record["record_type"], record["id"])
        self.assertEqual(reloaded["revision"], stored["revision"])
        self.assertEqual(reloaded, stored)

    def test_body_normalized_before_hashing(self):
        record = _sample_record(body="\n\nline with trailing space   \n\n\n")
        stored = self.store.create_record(record)
        self.assertEqual(stored["body"], "line with trailing space\n")
        self.assertEqual(stored["revision"], compute_revision(stored))


def _hold_write_lock(store_root: str, hold_seconds: float, ready_path: str) -> None:
    store = Store(Path(store_root))
    with store.write_lock():
        Path(ready_path).write_text("ready")
        time.sleep(hold_seconds)


class WriteLockContentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store_root = Path(self.tmp.name) / "store"
        self.store_root.mkdir(parents=True)

    def test_second_writer_fails_fast_while_first_holds_lock(self):
        ready_path = self.store_root / "ready.marker"
        ctx = multiprocessing.get_context("fork")
        holder = ctx.Process(
            target=_hold_write_lock,
            args=(str(self.store_root), 3.0, str(ready_path)),
        )
        holder.start()
        try:
            deadline = time.monotonic() + 5.0
            while not ready_path.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready_path.exists(), "holder process never acquired the lock")

            store = Store(self.store_root)
            start = time.monotonic()
            with self.assertRaises(StoreLockError) as ctx_err:
                with store.write_lock():
                    pass
            elapsed = time.monotonic() - start
            self.assertLess(elapsed, 3.0, "second writer should fail fast, not block for the full hold")
            self.assertIn(str(store.lock_path()), str(ctx_err.exception))
            self.assertIn(str(holder.pid), str(ctx_err.exception))
        finally:
            holder.join(timeout=5)
            if holder.is_alive():
                holder.terminate()
                holder.join(timeout=5)

    def test_lock_can_be_reacquired_after_release(self):
        store = Store(self.store_root)
        with store.write_lock():
            pass
        with store.write_lock():
            pass


class CliRoundTripTests(unittest.TestCase):
    """End-to-end check that the real create/get command path uses the new format."""

    def setUp(self):
        self.repo = make_git_repo()
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        self.store = self.repo / ".artifacts-record-file-test"

    def test_create_writes_frontmatter_file_and_get_round_trips(self):
        r = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

        r = run_cli(
            "create",
            "--type",
            "project:current-position",
            "--subject",
            "runtime",
            "--payload",
            json.dumps({"position": "building runtime", "scope": "design/runtime"}),
            store=self.store,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        created = load_json(r.stdout)["record"]

        path = (
            self.store
            / "records"
            / "project__current-position"
            / f"{created['id']}.md"
        )
        self.assertTrue(path.is_file())
        text = path.read_text()
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("\n---\n\n", text)

        r = run_cli("get", "--type", "project:current-position", "--id", created["id"], store=self.store)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        fetched = load_json(r.stdout)
        self.assertEqual(fetched, created)
        self.assertEqual(fetched.get("body"), "")


if __name__ == "__main__":
    unittest.main()
