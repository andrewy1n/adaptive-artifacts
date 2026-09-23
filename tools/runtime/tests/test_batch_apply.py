"""`apply -` executes many mutation ops from newline-delimited JSON on stdin
in a single process, instead of one CLI invocation (one process spawn) per
record. Failure semantics are continue-and-report: one bad line does not
abort the lines around it, and the aggregate result says which lines failed."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
sys.path.insert(0, str(RUNTIME))

from support import CLI, REPO_ROOT, RESOLVED, load_json, make_git_repo, run_cli  # noqa: E402


class BatchApplyTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.store = self.repo / ".batch-apply-test"
        self.addCleanup(lambda: shutil.rmtree(self.repo, ignore_errors=True))
        r = run_cli("init", store=self.store, contract=RESOLVED)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def _apply(self, ops: list[dict]) -> subprocess.CompletedProcess:
        stdin_text = "\n".join(json.dumps(op) for op in ops) + "\n"
        return subprocess.run(
            [sys.executable, str(CLI), "--store", str(self.store), "apply", "-"],
            input=stdin_text,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )

    def test_batch_create_in_one_process(self):
        ops = [
            {
                "op": "create",
                "type": "project:next-action",
                "subject": f"step-{i}",
                "payload": {"next": f"do step {i}", "scope": "design/runtime"},
            }
            for i in range(3)
        ]
        r = self._apply(ops)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        body = load_json(r.stdout)
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["applied"], 3)
        self.assertEqual(body["failed"], 0)
        self.assertEqual(len(body["results"]), 3)
        for result in body["results"]:
            self.assertEqual(result["op"], "create")
            self.assertEqual(result["record"]["record_type"], "project:next-action")

        listed = run_cli("list", "--type", "project:next-action", store=self.store)
        self.assertEqual(load_json(listed.stdout)["count"], 3)

    def test_one_bad_line_does_not_abort_the_rest(self):
        ops = [
            {
                "op": "create",
                "type": "project:next-action",
                "subject": "good-one",
                "payload": {"next": "do it", "scope": "design/runtime"},
            },
            {
                "op": "create",
                "type": "project:no-such-type",
                "subject": "bad-one",
                "payload": {},
            },
            {
                "op": "create",
                "type": "project:next-action",
                "subject": "good-two",
                "payload": {"next": "do it too", "scope": "design/runtime"},
            },
        ]
        r = self._apply(ops)
        self.assertNotEqual(r.returncode, 0)
        body = load_json(r.stdout)
        self.assertEqual(body["ok"], False)
        self.assertEqual(body["applied"], 2)
        self.assertEqual(body["failed"], 1)

        listed = run_cli("list", "--type", "project:next-action", store=self.store)
        self.assertEqual(load_json(listed.stdout)["count"], 2)


if __name__ == "__main__":
    unittest.main()
