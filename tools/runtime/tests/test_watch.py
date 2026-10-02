"""Tests for watch.run_watch: redraw a rendered view only when its text changes."""

from __future__ import annotations

import io
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
sys.path.insert(0, str(RUNTIME))

from support import run_cli  # noqa: E402
from watch import CLEAR, run_watch  # noqa: E402

VIEW = "# Dashboard\n\n## Work\n\n- **alpha** open\n"
CHANGED = "# Dashboard\n\n## Work\n\n- **beta** open\n"


class _Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += timedelta(seconds=seconds)


def _renderer(*results):
    queue = list(results)

    def render() -> str:
        result = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(result, BaseException):
            raise result
        return result

    return render


def _watch(render, *, iterations, width=lambda: 80, once=False, clock=None):
    clock = clock or _Clock()
    stream = io.StringIO()
    code = run_watch(
        render,
        stream=stream,
        sleep=clock.sleep,
        now=clock.now,
        width=width,
        interval=2.0,
        store_path="/tmp/store",
        max_iterations=iterations,
        once=once,
    )
    return code, stream.getvalue(), clock


class RunWatchTests(unittest.TestCase):
    def test_changed_render_redraws_once(self):
        code, out, _ = _watch(_renderer(VIEW, CHANGED), iterations=2)
        self.assertEqual(code, 0)
        self.assertEqual(out.count(CLEAR), 2)
        self.assertIn("beta", out.split(CLEAR)[-1])

    def test_unchanged_render_does_not_redraw(self):
        code, out, clock = _watch(_renderer(VIEW), iterations=5)
        self.assertEqual(code, 0)
        self.assertEqual(out.count(CLEAR), 1)
        self.assertEqual(clock.sleeps, [2.0] * 4)

    def test_header_shows_store_path_and_last_change_time(self):
        clock = _Clock()
        _, out, _ = _watch(_renderer(VIEW, VIEW, CHANGED), iterations=3, clock=clock)
        frames = out.split(CLEAR)[1:]
        self.assertEqual(len(frames), 2)
        header = frames[-1].splitlines()[0]
        self.assertIn("/tmp/store", header)
        self.assertIn("12:00:04", header)

    def test_width_change_counts_as_change(self):
        widths = iter([80, 80, 40])
        code, out, _ = _watch(_renderer(VIEW), iterations=3, width=lambda: next(widths))
        self.assertEqual(code, 0)
        self.assertEqual(out.count(CLEAR), 2)

    def test_render_error_shows_and_loop_continues(self):
        render = _renderer(RuntimeError("store locked"), RuntimeError("store locked"), VIEW)
        code, out, clock = _watch(render, iterations=3)
        self.assertEqual(code, 0)
        frames = out.split(CLEAR)[1:]
        self.assertEqual(len(frames), 2)
        self.assertIn("store locked", frames[0])
        self.assertIn("alpha", frames[1])
        self.assertEqual(len(clock.sleeps), 2)

    def test_keyboard_interrupt_during_sleep_exits_zero(self):
        def sleep(_seconds):
            raise KeyboardInterrupt

        stream = io.StringIO()
        code = run_watch(
            _renderer(VIEW),
            stream=stream,
            sleep=sleep,
            now=_Clock().now,
            width=lambda: 80,
            interval=2.0,
            store_path="/tmp/store",
        )
        self.assertEqual(code, 0)

    def test_keyboard_interrupt_during_render_exits_zero(self):
        code, _, _ = _watch(_renderer(KeyboardInterrupt()), iterations=3)
        self.assertEqual(code, 0)

    def test_once_prints_one_frame_without_sleeping(self):
        code, out, clock = _watch(_renderer(VIEW), iterations=None, once=True)
        self.assertEqual(code, 0)
        self.assertNotIn(CLEAR, out)
        self.assertEqual(out.count("/tmp/store"), 1)
        self.assertIn("Dashboard", out)
        self.assertIn("alpha", out)
        self.assertEqual(clock.sleeps, [])

    def test_once_render_error_exits_nonzero(self):
        code, out, _ = _watch(_renderer(RuntimeError("boom")), iterations=None, once=True)
        self.assertNotEqual(code, 0)
        self.assertIn("boom", out)


class WatchCliTests(unittest.TestCase):
    def test_rejects_non_positive_interval(self):
        for value in ("0", "-1"):
            result = run_cli("watch", "--id", "project:dashboard", "--interval", value)
            self.assertEqual(result.returncode, 2)
            self.assertIn("interval", result.stderr)


if __name__ == "__main__":
    unittest.main()
