"""Offline tests for ledger/build.py. Run: python3 -m unittest discover -s tests"""

import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ledger"))
import build  # noqa: E402

RSS = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Older story</title><link>https://example.com/old</link>
  <description>&lt;p&gt;Old &amp;amp;   boring&lt;/p&gt;</description>
  <pubDate>Mon, 19 Oct 2026 08:00:00 +0000</pubDate></item>
<item><title>Newer story&#8217;s &lt;script&gt; bug</title><link>https://example.com/new</link>
  <content:encoded><![CDATA[<p>Fresh <b>news</b></p>]]></content:encoded>
  <pubDate>Wed, 21 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>Evil link</title><link>javascript:alert(1)</link>
  <pubDate>Thu, 22 Oct 2026 08:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom story</title>
  <link rel="replies" href="https://example.org/a#comments"/>
  <link rel="alternate" href="https://example.org/a"/>
  <summary>Short</summary><published>2026-10-22T09:30:00.123+00:00</published></entry>
<entry><title>Syndicated</title><link href="https://example.com/new"/>
  <updated>2026-10-20T09:30:00Z</updated></entry>
</feed>"""


class ParseTests(unittest.TestCase):
    def test_rss_newest_first_and_non_http_links_dropped(self):
        articles = build.parse_feed(RSS)
        self.assertEqual([a.url for a in articles], ["https://example.com/new", "https://example.com/old"])

    def test_rss_text_cleanup(self):
        new, old = build.parse_feed(RSS)
        self.assertEqual(new.title, "Newer story’s <script> bug")  # literal < kept in titles
        self.assertEqual(new.summary, "Fresh news")
        self.assertEqual(old.summary, "Old & boring")
        self.assertEqual(new.published, datetime(2026, 10, 21, 8, tzinfo=timezone.utc))

    def test_atom_alternate_link_and_iso_dates(self):
        story, syndicated = build.parse_feed(ATOM)
        self.assertEqual(story.url, "https://example.org/a")
        self.assertEqual(story.published.minute, 30)
        self.assertEqual(syndicated.published.tzinfo, timezone.utc)

    def test_summary_truncates_on_word_boundary(self):
        self.assertEqual(build.summarize("alpha beta gamma", max_len=12), "alpha beta…")


class GatherTests(unittest.TestCase):
    def fetcher(self, url):
        if url == "down":
            raise OSError("connection refused")
        return {"rss": RSS, "atom": ATOM}[url]

    def test_dead_wire_reported_and_duplicates_skipped(self):
        dispatches, down = build.gather({"R": "rss", "Dead": "down", "A": "atom"}, 5, self.fetcher)
        self.assertEqual(down, ["Dead"])
        self.assertEqual([s for s, _ in dispatches], ["R", "A"])
        self.assertEqual([a.url for a in dispatches[1][1]], ["https://example.org/a"])

    def test_per_wire_limit(self):
        dispatches, _ = build.gather({"R": "rss"}, 1, self.fetcher)
        self.assertEqual(len(dispatches[0][1]), 1)


KEV = json.dumps({"vulnerabilities": [
    {"cveID": "CVE-2026-0001", "vulnerabilityName": "Old Thing RCE", "dateAdded": "2026-09-01",
     "shortDescription": "Ancient.", "dueDate": "2026-09-22", "knownRansomwareCampaignUse": "Unknown",
     "notes": "https://nvd.nist.gov/vuln/detail/CVE-2026-0001", "cwes": []},
    {"cveID": "CVE-2026-1111", "vulnerabilityName": "Widget <b>Auth</b> Bypass", "dateAdded": "2026-10-15",
     "shortDescription": "Bypass.", "dueDate": "2026-11-05", "knownRansomwareCampaignUse": "Unknown",
     "notes": " ; https://www.cisa.gov/bod ; https://vendor.example/advisory-1 ; https://nvd.nist.gov/x",
     "cwes": ["CWE-287", "not-a-cwe"]},
    {"cveID": "CVE-2026-2222", "vulnerabilityName": "Gadget SQLi", "dateAdded": "2026-10-21",
     "shortDescription": "SQL injection.", "dueDate": "2026-11-11", "knownRansomwareCampaignUse": "Known",
     "notes": "javascript:alert(1)", "cwes": ["CWE-89"]},
    {"cveID": "CVE-2026-3333", "vulnerabilityName": "Gizmo XSS", "dateAdded": "2026-10-21",
     "shortDescription": "XSS.", "dueDate": "", "knownRansomwareCampaignUse": "Unknown", "notes": "", "cwes": []},
    {"cveID": "<script>", "vulnerabilityName": "Bogus", "dateAdded": "2026-10-21"},
    {"cveID": "CVE-2026-4444", "vulnerabilityName": "No date", "dateAdded": "soon"},
]}).encode()


class KevTests(unittest.TestCase):
    def setUp(self):
        self.entries = {e.cve: e for e in build.parse_kev(KEV)}

    def test_parse_skips_bad_ids_and_dates(self):
        self.assertEqual(sorted(self.entries), ["CVE-2026-0001", "CVE-2026-1111", "CVE-2026-2222", "CVE-2026-3333"])

    def test_parse_fields(self):
        widget = self.entries["CVE-2026-1111"]
        self.assertEqual(widget.advisory, "https://vendor.example/advisory-1")
        self.assertEqual(widget.cwes, ["CWE-287"])
        self.assertFalse(widget.ransomware)
        self.assertTrue(self.entries["CVE-2026-2222"].ransomware)
        self.assertEqual(self.entries["CVE-2026-2222"].advisory, "")
        self.assertIsNone(self.entries["CVE-2026-3333"].due)

    def test_fresh_additions_win_and_rotate_daily(self):
        entries = list(self.entries.values())
        day1, recent = build.pick_kev(entries, date(2026, 10, 22))
        day2, _ = build.pick_kev(entries, date(2026, 10, 23))
        self.assertIn(day1.cve, {"CVE-2026-2222", "CVE-2026-3333"})
        self.assertIn(day2.cve, {"CVE-2026-2222", "CVE-2026-3333"})
        self.assertNotEqual(day1.cve, day2.cve)
        self.assertEqual(recent, 3)  # Sep 1 is outside the 30-day window

    def test_quiet_days_rotate_through_recent(self):
        entries = list(self.entries.values())
        seen = {build.pick_kev(entries, date(2026, 11, 1) + timedelta(days=i))[0].cve for i in range(6)}
        self.assertEqual(seen, {"CVE-2026-1111", "CVE-2026-2222", "CVE-2026-3333"})

    def test_empty_window(self):
        self.assertEqual(build.pick_kev(list(self.entries.values()), date(2027, 6, 1)), (None, 0))

    def test_feed_outage_is_not_fatal(self):
        def broken(url, **kwargs):
            raise OSError("timed out")
        self.assertEqual(build.todays_kev(date(2026, 10, 22), broken), (None, 0))

    def test_render_bulletin(self):
        html_out = build.render_kev(self.entries["CVE-2026-1111"], 3)
        self.assertIn('href="https://nvd.nist.gov/vuln/detail/CVE-2026-1111"', html_out)
        self.assertIn("Widget &lt;b&gt;Auth&lt;/b&gt; Bypass", html_out)
        self.assertIn("https://vendor.example/advisory-1", html_out)
        self.assertIn("One of 3 vulnerabilities", html_out)
        self.assertNotIn('class="alarm"', html_out)
        self.assertIn('class="alarm">Known', build.render_kev(self.entries["CVE-2026-2222"], 1))
        self.assertEqual(build.render_kev(None, 0), "")


class RenderTests(unittest.TestCase):
    def test_markup_in_feeds_is_escaped(self):
        evil = build.Article(
            title='</script><img src=x onerror="alert(1)">',
            url='https://example.com/?a=1&b="2"',
            summary="<b>bold</b>",
            published=None,
        )
        page = build.render([("Wire <i>", [evil])], ["Down & out"], datetime(2026, 10, 23, tzinfo=timezone.utc))
        self.assertNotIn("<img", page)
        self.assertNotIn("<b>bold", page)
        self.assertNotIn("<i>", page)
        self.assertIn("&lt;/script&gt;&lt;img", page)
        self.assertIn('href="https://example.com/?a=1&amp;b=&quot;2&quot;"', page)
        self.assertIn("1 of 2 wires live", page)
        self.assertIn("Down &amp; out", page)
        self.assertIn("No. 2", page)


if __name__ == "__main__":
    unittest.main()
