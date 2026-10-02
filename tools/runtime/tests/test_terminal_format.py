"""Tests for terminal.format_view: rendered view markdown to terminal text."""

from __future__ import annotations

import io
import re
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
RUNTIME = TESTS.parent
REPO_ROOT = RUNTIME.parent.parent
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(REPO_ROOT))

from handoff import generate_view  # noqa: E402
from terminal import BOLD, EMPTY_STATE, RESET, color_enabled, format_view  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _record(record_id, subject, **payload):
    return {
        "id": record_id,
        "record_type": "project:work-item",
        "subject": subject,
        "lifecycle_state": "open",
        "payload": payload,
    }


def _contract():
    return {
        "views": [
            {
                "id": "project:dashboard",
                "roles": [
                    {
                        "name": "work",
                        "occupant": "project:work-item",
                        "selection": {"all": []},
                        "requires_payload": ["title", "owner"],
                    }
                ],
            }
        ]
    }


def _dashboard(records):
    return generate_view(_contract(), "project:dashboard", records)


RECORDS = [
    _record("rec-aaaa", "alpha", title="First task with a fairly long title that goes on"),
    _record("rec-bbbb", "beta", title="Second", owner="ayin"),
    _record("rec-cccc", "gamma"),
]


class FormatViewTests(unittest.TestCase):
    def test_drops_banner_and_id_suffixes(self):
        out = format_view(_dashboard(RECORDS), width=200, color=False)
        self.assertNotIn("Derived view", out)
        self.assertNotIn("Store state", out)
        self.assertNotIn("id:", out)
        self.assertNotIn("rec-", out)
        self.assertNotIn("_(", out)
        self.assertIn("alpha", out)
        self.assertIn("gamma", out)

    def test_keeps_owner_when_id_suffix_is_dropped(self):
        out = format_view(_dashboard(RECORDS), width=200, color=False)
        beta = next(line for line in out.splitlines() if line.startswith("- beta"))
        self.assertIn("owner: ayin", beta)

    def test_headings_plain_without_color(self):
        out = format_view(_dashboard(RECORDS), width=200, color=False)
        self.assertNotIn("\x1b[", out)
        lines = out.splitlines()
        self.assertEqual(lines[0], "# Project Dashboard")
        self.assertIn("## alpha", lines)
        self.assertIn("### Work", lines)

    def test_headings_bold_with_color(self):
        out = format_view(_dashboard(RECORDS), width=200, color=True)
        lines = out.splitlines()
        self.assertEqual(lines[0], f"{BOLD}# Project Dashboard{RESET}")
        self.assertIn(f"{BOLD}## alpha{RESET}", lines)
        for line in lines:
            if line.startswith("- "):
                self.assertNotIn("\x1b[", line)

    def test_no_line_exceeds_width(self):
        for color in (False, True):
            out = format_view(_dashboard(RECORDS), width=20, color=color)
            for line in out.splitlines():
                self.assertLessEqual(len(ANSI.sub("", line)), 20, line)
            self.assertIn("…", out)

    def test_truncated_bold_heading_still_resets(self):
        out = format_view("# A very long heading title\n", width=10, color=True)
        self.assertEqual(out.splitlines()[0], f"{BOLD}# A very …{RESET}")

    def test_short_line_is_not_truncated(self):
        out = format_view("# Hi\n\n## g\n\n- x\n", width=4, color=False)
        self.assertEqual(out.splitlines(), ["# Hi", "", "## g", "", "- x"])

    def test_empty_view_gives_empty_state_line(self):
        out = format_view(_dashboard([]), width=80, color=False)
        self.assertEqual(out.splitlines(), ["# Project Dashboard", "", EMPTY_STATE])

    def test_view_without_record_lines_gives_empty_state_line(self):
        self.assertEqual(format_view("", width=80, color=False), EMPTY_STATE)


class _Stream(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self._tty = tty

    def isatty(self):
        return self._tty


class ColorEnabledTests(unittest.TestCase):
    def test_tty_without_no_color_is_on(self):
        self.assertTrue(color_enabled(_Stream(True), environ={}))

    def test_no_color_set_is_off(self):
        self.assertFalse(color_enabled(_Stream(True), environ={"NO_COLOR": "1"}))

    def test_not_a_tty_is_off(self):
        self.assertFalse(color_enabled(_Stream(False), environ={}))


if __name__ == "__main__":
    unittest.main()
