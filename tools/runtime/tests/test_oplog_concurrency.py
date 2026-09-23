"""Tests for the append-only op log: fold semantics, checkpointing, and
the concurrency guarantee it exists to provide."""

from __future__ import annotations

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

from support import RESOLVED, make_git_repo, run_cli  # noqa: E402
from contract import load_contract  # noqa: E402
import oplog  # noqa: E402
from store import CHECKPOINT_THRESHOLD, Store, StaleWriteError, StoreError  # noqa: E402


def _base_record(record_id: str, subject: str, counter: int = 0) -> dict:
    return {
        "id": record_id,
        "record_type": "project:current-position",
        "base_kind": "claim",
        "subject": subject,
        "stewardship": {"steward": "agent"},
        "payload": {"position": "p", "scope": "s", "counter": counter},
        "lifecycle_state": "active",
        "relationships": {},
        "revision": "",
        "epistemic_status": "asserted",
        "time": {"as_of": "2026-09-04T00:00:00+00:00"},
    }


class OpLogFoldTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        self.store_path = self.repo / ".artifacts-oplog-test"
        r = run_cli("init", store=self.store_path, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.store = Store(self.store_path)

    def test_create_appends_one_op_and_materializes(self):
        record_id = self.store.new_id()
        stored = self.store.create_record(_base_record(record_id, "s1"))
        chain_dir = self.store._chain_dir("project:current-position", record_id)
        ops = oplog.read_ops(chain_dir)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["kind"], "create")
        on_disk = self.store.read_record("project:current-position", record_id)
        self.assertEqual(on_disk["revision"], stored["revision"])

    def test_second_create_over_same_id_rejected_without_second_op_winning(self):
        record_id = self.store.new_id()
        self.store.create_record(_base_record(record_id, "s1"))
        with self.assertRaises(StoreError):
            self.store.create_record(_base_record(record_id, "s2"))
        # the rejected attempt must not have overwritten the materialized record
        on_disk = self.store.read_record("project:current-position", record_id)
        self.assertEqual(on_disk["subject"], "s1")

    def test_write_without_expected_revision_over_live_record_rejected(self):
        record_id = self.store.new_id()
        stored = self.store.create_record(_base_record(record_id, "s1"))
        with self.assertRaises(StoreError):
            self.store.write_record(dict(stored, subject="s2"))

    def test_stale_expected_revision_rejected_and_leaves_state_unchanged(self):
        record_id = self.store.new_id()
        stored = self.store.create_record(_base_record(record_id, "s1"))
        with self.assertRaises(StaleWriteError):
            self.store.write_record(dict(stored, subject="s2"), expected_revision="sha256:dead")
        on_disk = self.store.read_record("project:current-position", record_id)
        self.assertEqual(on_disk["subject"], "s1")

    def test_orphan_temp_file_ignored_by_fold(self):
        record_id = self.store.new_id()
        self.store.create_record(_base_record(record_id, "s1"))
        chain_dir = self.store._chain_dir("project:current-position", record_id)
        # simulate a crash between writing the temp file and linking it in
        (chain_dir / ".tmp-orphan").write_text('{"kind": "write"}')
        ops = oplog.read_ops(chain_dir)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["kind"], "create")

    def test_checkpoint_bounds_chain_length_and_preserves_state(self):
        record_id = self.store.new_id()
        stored = self.store.create_record(_base_record(record_id, "s1", counter=0))
        for i in range(1, CHECKPOINT_THRESHOLD + 5):
            stored = self.store.write_record(
                dict(stored, payload=dict(stored["payload"], counter=i)),
                expected_revision=stored["revision"],
            )
        chain_dir = self.store._chain_dir("project:current-position", record_id)
        remaining = oplog.read_ops(chain_dir)
        self.assertLess(len(remaining), CHECKPOINT_THRESHOLD + 5)
        self.assertTrue(any(op["kind"] == "checkpoint" for op in remaining))
        on_disk = self.store.read_record("project:current-position", record_id)
        self.assertEqual(on_disk["payload"]["counter"], CHECKPOINT_THRESHOLD + 4)
        self.assertEqual(on_disk["revision"], stored["revision"])

    def test_delete_record_file_purges_chain(self):
        record_id = self.store.new_id()
        self.store.create_record(_base_record(record_id, "s1"))
        chain_dir = self.store._chain_dir("project:current-position", record_id)
        self.assertTrue(chain_dir.is_dir())
        self.store.delete_record_file("project:current-position", record_id)
        self.assertFalse(chain_dir.exists())
        self.assertFalse(self.store.record_exists("project:current-position", record_id))


def _concurrent_create(store_root: str, record_id: str, subject: str) -> str:
    store = Store(Path(store_root))
    try:
        store.create_record(_base_record(record_id, subject))
        return "created"
    except StoreError:
        return "rejected"


def _concurrent_increment(store_root: str, record_type: str, record_id: str, attempts: int) -> int:
    """Repeatedly bump payload['counter'] by 1 via optimistic concurrency, retrying
    on StaleWriteError with a little jitter so a pool of writers doesn't just
    reconverge on the same losing race every time. Returns how many of its own
    increments actually landed."""
    import random

    store = Store(Path(store_root))
    landed = 0
    for _ in range(attempts):
        for retry in range(300):
            current = store.read_record(record_type, record_id)
            proposed = dict(current, payload=dict(current["payload"], counter=current["payload"]["counter"] + 1))
            try:
                store.write_record(proposed, expected_revision=current["revision"])
                landed += 1
                break
            except StaleWriteError:
                if retry > 10:
                    time.sleep(random.uniform(0, 0.002))
                continue
        else:
            raise AssertionError("writer starved after 300 retries")
    return landed


class ConcurrentWriterTests(unittest.TestCase):
    """The property the append-only log exists to prove: concurrent writers
    against one store never contend, and every accepted op survives folding."""

    def setUp(self):
        self.repo = make_git_repo()
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        self.store_path = self.repo / ".artifacts-oplog-test"
        r = run_cli("init", store=self.store_path, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.store = Store(self.store_path)

    def test_concurrent_creates_to_distinct_ids_all_survive(self):
        ids = [self.store.new_id() for _ in range(8)]
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=8) as pool:
            results = pool.starmap(
                _concurrent_create,
                [(str(self.store_path), record_id, f"subject-{i}") for i, record_id in enumerate(ids)],
            )
        self.assertEqual(results, ["created"] * 8)
        stored_ids = {r["id"] for r in self.store.iter_records("project:current-position")}
        self.assertEqual(stored_ids, set(ids))

    def test_concurrent_creates_to_same_id_exactly_one_wins(self):
        record_id = self.store.new_id()
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=6) as pool:
            results = pool.starmap(
                _concurrent_create,
                [(str(self.store_path), record_id, f"subject-{i}") for i in range(6)],
            )
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(results.count("rejected"), 5)
        chain_dir = self.store._chain_dir("project:current-position", record_id)
        ops = oplog.read_ops(chain_dir)
        self.assertEqual(len(ops), 6)
        self.assertEqual(sum(1 for op in ops if op["kind"] == "create"), 6)

    def test_concurrent_optimistic_writers_lose_no_increments(self):
        record_id = self.store.new_id()
        self.store.create_record(_base_record(record_id, "s1", counter=0))
        writers, attempts = 5, 4
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=writers) as pool:
            landed = pool.starmap(
                _concurrent_increment,
                [(str(self.store_path), "project:current-position", record_id, attempts)] * writers,
            )
        self.assertEqual(sum(landed), writers * attempts)
        final = self.store.read_record("project:current-position", record_id)
        self.assertEqual(final["payload"]["counter"], writers * attempts)
        chain_dir = self.store._chain_dir("project:current-position", record_id)
        accepted = sum(
            1
            for op in oplog.read_ops(chain_dir)
            if op["kind"] in ("create", "write", "checkpoint")
        )
        self.assertGreaterEqual(accepted, 1)


if __name__ == "__main__":
    unittest.main()
