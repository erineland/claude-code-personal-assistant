import datetime
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hooks"))
import append_only_guard as guard  # noqa: E402
import browser_action_guard as browser  # noqa: E402
import session_start_handoff as handoff  # noqa: E402

NOTE = """---
updated: 2030-01-01
---
# Alex

## 💛 What lights them up
- climbing

## 🗓 Log
### 2030-01-01 · coffee
- talked about the new job
"""


def run(fn, *args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(*args)
    out = buf.getvalue().strip()
    return json.loads(out)["hookSpecificOutput"] if out else None


class AppendOnlyGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notes = os.path.join(self.tmp.name, "People")
        self.digest = os.path.join(self.tmp.name, "Digest")
        os.makedirs(self.notes)
        os.makedirs(self.digest)
        self.path = os.path.join(self.notes, "Alex.md")
        with open(self.path, "w") as f:
            f.write(NOTE)

    def tearDown(self):
        self.tmp.cleanup()

    def edit(self, old, new, path=None):
        event = {"tool_name": "Edit",
                 "tool_input": {"file_path": path or self.path, "old_string": old, "new_string": new}}
        return run(guard.check, event, self.notes, [self.digest])

    def test_new_log_entry_and_updated_bump_allowed(self):
        self.assertIsNone(self.edit("## 🗓 Log\n", "## 🗓 Log\n### 2030-01-02 · walk\n- went for a walk\n"))
        self.assertIsNone(self.edit("updated: 2030-01-01", "updated: 2030-01-02"))

    def test_curated_section_change_refused(self):
        out = self.edit("- climbing", "- climbing and bouldering")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("above the log", out["permissionDecisionReason"])

    def test_rewriting_old_log_refused(self):
        out = self.edit("- talked about the new job", "- talked")
        self.assertEqual(out["permissionDecision"], "deny")

    def test_paths_outside_refused_and_dotdot_refused(self):
        out = self.edit("x", "y", path=os.path.join(self.tmp.name, "other.md"))
        self.assertEqual(out["permissionDecision"], "deny")
        out = self.edit("x", "y", path=os.path.join(self.notes, "..", "other.md"))
        self.assertEqual(out["permissionDecision"], "deny")

    def test_digest_folder_is_free(self):
        event = {"tool_name": "Write",
                 "tool_input": {"file_path": os.path.join(self.digest, "week.md"), "content": "hi"}}
        self.assertIsNone(run(guard.check, event, self.notes, [self.digest]))

    def test_new_note_refused(self):
        event = {"tool_name": "Write",
                 "tool_input": {"file_path": os.path.join(self.notes, "Robin.md"), "content": "x"}}
        self.assertEqual(run(guard.check, event, self.notes, [self.digest])["permissionDecision"], "deny")

    def test_unknown_tool_refused(self):
        event = {"tool_name": "MultiEdit",
                 "tool_input": {"file_path": self.path, "edits": [{"old_string": "- climbing", "new_string": ""}]}}
        self.assertEqual(run(guard.check, event, self.notes, [self.digest])["permissionDecision"], "deny")


class BrowserGuardTests(unittest.TestCase):
    T = "mcp__playwright__"

    def test_reading_is_free(self):
        self.assertIsNone(browser.verdict(self.T + "browser_snapshot", {}))
        self.assertIsNone(browser.verdict(self.T + "browser_click", {"element": "Next page link"}))

    def test_outward_actions_ask(self):
        self.assertTrue(browser.verdict(self.T + "browser_click", {"element": "Place order button"}))
        self.assertTrue(browser.verdict(self.T + "browser_click", {"ref": "e12"}))
        self.assertTrue(browser.verdict(self.T + "browser_press_key", {"key": "Enter"}))
        for chord in ("Control+Enter", "Meta+Enter", "Shift+Control+NumpadEnter"):
            self.assertTrue(browser.verdict(self.T + "browser_press_key", {"key": chord}), chord)
        self.assertIsNone(browser.verdict(self.T + "browser_press_key", {"key": "Control+a"}))
        self.assertTrue(browser.verdict(self.T + "browser_evaluate", {"function": "() => fetch('/x')"}))

    def test_unknown_action_asks(self):
        self.assertTrue(browser.verdict(self.T + "browser_drag", {"startElement": "a", "endElement": "b"}))


class HandoffTests(unittest.TestCase):
    def test_finds_newest_handoff_within_lookback(self):
        with tempfile.TemporaryDirectory() as d:
            today = datetime.date(2030, 1, 10)
            with open(os.path.join(d, "2030-01-09.md"), "w") as f:
                f.write("# Diary\n\n## 🔁 Handoff\n**In flight**\n- thing\n\n## 🌙 Evening wrap\nbye\n")
            with mock.patch.object(handoff, "DIARY", d):
                path, body = handoff.find_handoff(today)
            self.assertTrue(path.endswith("2030-01-09.md"))
            self.assertEqual(body, "**In flight**\n- thing")


if __name__ == "__main__":
    unittest.main()
