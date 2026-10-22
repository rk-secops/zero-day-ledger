"""Tests for ledger/log.py: alerts become Actions annotations only inside Actions."""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ledger"))
import log  # noqa: E402


class LogTests(unittest.TestCase):
    def capture(self, fn, message, env):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out), redirect_stderr(err):
            fn(message)
        return out.getvalue(), err.getvalue()

    def test_alert_is_an_annotation_in_actions(self):
        out, err = self.capture(log.alert, "Wire down: 100% gone\nreally", {"GITHUB_ACTIONS": "true"})
        self.assertEqual(out, "::warning title=Zero-Day Ledger::Wire down: 100%25 gone%0Areally\n")
        self.assertEqual(err, "")

    def test_alert_is_plain_text_locally(self):
        out, err = self.capture(log.alert, "Wire down", {})
        self.assertEqual((out, err), ("", "[alert] Wire down\n"))

    def test_warn_never_annotates(self):
        out, err = self.capture(log.warn, "blocked", {"GITHUB_ACTIONS": "true"})
        self.assertEqual((out, err), ("", "[warn] blocked\n"))

    def test_summary_appends_only_in_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.md"
            with mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(path)}, clear=True):
                log.summary("### One")
                log.summary("- two\n")
            self.assertEqual(path.read_text(), "### One\n- two\n")
            with mock.patch.dict(os.environ, {}, clear=True):
                log.summary("ignored")


if __name__ == "__main__":
    unittest.main()
