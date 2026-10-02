"""Run the real `watch` CLI in a pseudo-terminal against a temp store."""

from __future__ import annotations

import os
import select
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
sys.path.insert(0, str(RUNTIME))

from support import (  # noqa: E402
    CLI,
    REPO_ROOT,
    RESOLVED,
    make_git_repo,
    run_cli,
    sample_goal_payload,
    sample_next_payload,
)
from watch import CLEAR  # noqa: E402

try:
    import pty  # noqa: F401
except ImportError:
    pty = None

CLEAR_BYTES = CLEAR.encode()
VIEW_ID = "project:handoff"
FIRST_SUBJECT = "watch-integration-first"
NEW_SUBJECT = "watch-integration-new"


@unittest.skipIf(pty is None or not hasattr(os, "openpty"), "needs a pty")
class WatchIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_git_repo()
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.store = self.repo / ".watch-test"
        self._cli_ok("init", contract=RESOLVED)
        self._cli_ok("create", "--type", "project:active-goal", "--subject", FIRST_SUBJECT,
                     "--payload", sample_goal_payload())
        self.output = b""

    def _cli_ok(self, *args, contract=None):
        result = run_cli(*args, store=self.store, contract=contract)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def _start_watch(self) -> subprocess.Popen:
        self.master, slave = os.openpty()
        self.addCleanup(os.close, self.master)
        env = dict(os.environ, COLUMNS="100", LINES="40", NO_COLOR="1")
        proc = subprocess.Popen(
            [sys.executable, str(CLI), "--store", str(self.store),
             "watch", "--id", VIEW_ID, "--interval", "0.2"],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=str(REPO_ROOT),
            env=env,
            close_fds=True,
        )
        os.close(slave)
        self.addCleanup(self._reap, proc)
        return proc

    def _reap(self, proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    def _read(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            ready, _, _ = select.select([self.master], [], [], remaining)
            if not ready:
                return
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                return
            if not chunk:
                return
            self.output += chunk

    def _read_until(self, predicate, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while not predicate():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._read(min(remaining, 0.05))
        return True

    def _frames(self) -> int:
        return self.output.count(CLEAR_BYTES)

    def test_watch_integration_redraws_on_write_and_exits_zero_on_sigint(self):
        proc = self._start_watch()

        shown = self._read_until(
            lambda: self._frames() >= 1 and FIRST_SUBJECT.encode() in self.output, 5.0
        )
        self.assertTrue(shown, self.output.decode(errors="replace"))
        self.assertEqual(self._frames(), 1)

        self._read(1.0)
        self.assertEqual(self._frames(), 1, "watch redrew while the store was idle")

        self._cli_ok("create", "--type", "project:next-action", "--subject", NEW_SUBJECT,
                     "--payload", sample_next_payload())
        written_at = time.monotonic()
        redrawn = self._read_until(
            lambda: self._frames() >= 2
            and NEW_SUBJECT.encode() in self.output.rsplit(CLEAR_BYTES, 1)[-1],
            3.0,
        )
        self.assertTrue(redrawn, self.output.decode(errors="replace"))
        self.assertLess(time.monotonic() - written_at, 3.0)

        proc.send_signal(signal.SIGINT)
        try:
            code = proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self.fail("watch did not exit within 2 s of SIGINT")
        self.assertEqual(code, 0, self.output.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
