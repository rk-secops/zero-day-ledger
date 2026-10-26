"""Offline tests for tools/watchdog.py's checks."""

import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import watchdog  # noqa: E402

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
STORY = '<article class="article"><h3>x</h3></article>\n'


def page(built="2026-10-23T11:00+00:00", extra="", stories=6):
    return (f'<script src="typewriter.js" defer></script>{extra}'
            f'<h1 class="title">The <span class="nowrap">Zero-Day</span> Ledger</h1>'
            f'<div class="dateline">\n      <time datetime="{built}">Friday</time></div>'
            + STORY * stories).encode()


class HeaderTests(unittest.TestCase):
    def test_parses_the_real_headers_file(self):
        expected = watchdog.expected_headers((ROOT / "static" / "_headers").read_text())
        self.assertIn("script-src 'self'", expected["content-security-policy"])
        self.assertIn("strict-transport-security", expected)
        self.assertNotIn("cache-control", expected)  # per-path blocks are not global

    def test_missing_and_changed_headers(self):
        expected = {"x-content-type-options": "nosniff", "content-security-policy": "default-src 'none'"}
        problems = watchdog.check_headers({"Content-Security-Policy": "default-src *"}, expected)
        self.assertEqual(len(problems), 2)
        self.assertEqual(watchdog.check_headers({"x-content-type-options": "nosniff",
                                                 "content-security-policy": "default-src 'none'"}, expected), [])


class PageTests(unittest.TestCase):
    def test_healthy_page(self):
        self.assertEqual(watchdog.check_page(page(), NOW), [])

    def test_all_page_scripts_allowed(self):
        template = (ROOT / "ledger" / "template.html").read_text()
        scripts = ''.join(re.findall(r'<script\b[^>]*></script>', template))
        self.assertEqual(scripts.count("<script"), len(watchdog.ALLOWED_SCRIPTS))
        self.assertEqual(watchdog.check_page(page(extra=scripts), NOW), [])

    def test_injected_script_and_iframe(self):
        problems = watchdog.check_page(page(extra='<script src="https://evil.example/x.js"></script>'
                                                  '<script>alert(1)</script><iframe src="x">'), NOW)
        self.assertEqual(sum("unexpected script" in p for p in problems), 2)
        self.assertTrue(any("iframe" in p for p in problems))

    def test_stale_edition_and_missing_stories(self):
        problems = watchdog.check_page(page(built="2026-10-21T11:00+00:00", stories=2), NOW)
        self.assertTrue(any("stale" in p for p in problems))
        self.assertTrue(any("only 2 stories" in p for p in problems))

    def test_defaced_page(self):
        problems = watchdog.check_page(b"<h1>hacked</h1>", NOW)
        self.assertTrue(any("masthead" in p for p in problems))


class OtherChecks(unittest.TestCase):
    def test_redirect(self):
        self.assertEqual(watchdog.check_redirect(301, {"Location": "https://thezerodayledger.com/"}), [])
        self.assertTrue(watchdog.check_redirect(200, {}))
        self.assertTrue(watchdog.check_redirect(301, {"Location": "https://evil.example/"}))

    def test_security_txt_expiry(self):
        ok = b"Contact: x\nExpires: 2027-10-22T00:00:00Z\n"
        soon = b"Expires: 2026-11-01T00:00:00Z\n"
        self.assertEqual(watchdog.check_security_txt(200, ok, NOW), [])
        self.assertTrue(watchdog.check_security_txt(200, soon, NOW))
        self.assertTrue(watchdog.check_security_txt(404, b"", NOW))

    def test_summaries_and_cert(self):
        self.assertEqual(watchdog.check_summaries(200, b'{"summaries": {}}'), [])
        self.assertTrue(watchdog.check_summaries(200, b"<html>"))
        self.assertEqual(watchdog.check_cert(NOW + timedelta(days=60), NOW), [])
        self.assertTrue(watchdog.check_cert(NOW + timedelta(days=3), NOW))


if __name__ == "__main__":
    unittest.main()
