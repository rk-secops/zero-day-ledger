"""Offline tests for ledger/summarize.py. No network, no API key: the SDK is stubbed."""

import json
import os
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ledger"))
import build  # noqa: E402
import summarize as ai  # noqa: E402

LONG = "Attackers exploited a flaw in the widget gateway to steal session tokens. " * 10

PAGE = f"""<html><head><script>var p = "<p>not this</p>";</script></head><body>
<nav><p>Home | News | Subscribe to our newsletter today</p></nav>
<article><h1>Big breach</h1><p>{LONG}</p><p>Short</p>
<p>Vendor &amp; partners say patches are out for all supported versions now.</p></article>
<footer><p>Copyright 2026 Example Media, all rights reserved worldwide.</p></footer>
</body></html>""".encode()


def article(url="https://example.com/a", body=""):
    return build.Article(title="Big breach", url=url, summary="Feed blurb", published=None, body=body)


class ExtractTests(unittest.TestCase):
    def test_keeps_article_paragraphs_only(self):
        text = ai.extract_text(PAGE)
        self.assertIn("widget gateway", text)
        self.assertIn("Vendor & partners", text)
        self.assertNotIn("not this", text)
        self.assertNotIn("newsletter", text)
        self.assertNotIn("Copyright", text)
        self.assertNotIn("Short", text)

    def test_source_prefers_the_fuller_text(self):
        page = ai.source_text(article(body="tiny feed text"), lambda url, **kw: PAGE)
        self.assertIn("widget gateway", page)

    def test_source_falls_back_to_feed_when_site_blocks(self):
        def blocked(url, **kw):
            raise OSError("HTTP Error 403: Forbidden")
        self.assertEqual(ai.source_text(article(body=LONG), blocked), LONG)

    def test_thin_sources_are_skipped(self):
        self.assertEqual(ai.source_text(article(body="teaser"), lambda url, **kw: b"<p>paywall</p>"), "")

    def test_long_articles_are_capped(self):
        text = ai.source_text(article(body="word " * 20_000), lambda url, **kw: b"")
        self.assertEqual(len(text), ai.MAX_ARTICLE_CHARS)


class CacheTests(unittest.TestCase):
    def test_load_validates_entries(self):
        doc = {"model": "x", "summaries": {
            "https://a": "Good summary.", "https://b": "", "https://c": 42, "https://d": "x" * 5000}}
        cache = ai.load_cache(lambda url, **kw: json.dumps(doc).encode())
        self.assertEqual(cache, {"https://a": "Good summary."})

    def test_missing_or_garbled_cache_is_empty(self):
        def down(url, **kw):
            raise OSError("404")
        self.assertEqual(ai.load_cache(down), {})
        self.assertEqual(ai.load_cache(lambda url, **kw: b"not json"), {})
        self.assertEqual(ai.load_cache(lambda url, **kw: b"[1, 2]"), {})

    def test_cache_document_holds_only_todays_summaries(self):
        a, b = article("https://a"), article("https://b")
        a.ai_summary = "Summary A."
        doc = json.loads(ai.cache_document([("Wire", [a, b])]))
        self.assertEqual(doc["summaries"], {"https://a": "Summary A."})
        self.assertEqual(doc["model"], ai.MODEL)


class AddSummariesTests(unittest.TestCase):
    def test_reuses_cache_and_writes_only_new_stories(self):
        old, new, thin = article("https://old"), article("https://new", LONG), article("https://thin")
        calls = []

        def writer(source, art, text):
            calls.append(art.url)
            return f"Summary of {art.url}."

        reused, written = ai.add_summaries(
            [("Wire", [old, new, thin])], writer,
            fetcher=lambda url, **kw: b"", cache={"https://old": "Cached."})
        self.assertEqual((reused, written), (1, 1))
        self.assertEqual(calls, ["https://new"])
        self.assertEqual(old.ai_summary, "Cached.")
        self.assertEqual(new.ai_summary, "Summary of https://new.")
        self.assertEqual(thin.ai_summary, "")

    def test_without_writer_cache_still_applies(self):
        a = article("https://old")
        self.assertEqual(ai.add_summaries([("W", [a])], None, lambda u, **k: b"", {"https://old": "C."}), (1, 0))
        self.assertEqual(a.ai_summary, "C.")

    def test_clean_summary(self):
        self.assertEqual(ai.clean_summary("  Summary:  Two\n sentences. "), "Two sentences.")
        self.assertTrue(ai.clean_summary("word " * 300).endswith("…"))
        self.assertLessEqual(len(ai.clean_summary("word " * 300)), ai.MAX_SUMMARY_CHARS + 1)


def fake_sdk(response=None, error=None):
    """A stand-in for the anthropic module that records create() calls."""
    sdk = types.ModuleType("anthropic")

    class APIStatusError(Exception):
        def __init__(self, status_code, message="boom"):
            super().__init__(message)
            self.status_code, self.message = status_code, message

    class AuthenticationError(APIStatusError):
        pass

    class PermissionDeniedError(APIStatusError):
        pass

    class APIConnectionError(Exception):
        pass

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if error:
            raise error(sdk)
        return response

    class Anthropic:
        def __init__(self, **kwargs):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))

    sdk.__dict__.update(Anthropic=Anthropic, APIStatusError=APIStatusError, AuthenticationError=AuthenticationError,
                        PermissionDeniedError=PermissionDeniedError, APIConnectionError=APIConnectionError)
    return sdk, calls


def response(stop_reason="end_turn", text="Two sentences about it.", category=None):
    return types.SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=types.SimpleNamespace(category=category) if category else None,
        content=[types.SimpleNamespace(type="thinking", thinking=""), types.SimpleNamespace(type="text", text=text)],
    )


class WriterTests(unittest.TestCase):
    def writer(self, sdk):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}), \
             mock.patch.dict(sys.modules, {"anthropic": sdk}):
            return ai.make_writer()

    def test_no_key_no_writer(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(ai.make_writer())

    def test_request_shape(self):
        sdk, calls = fake_sdk(response())
        self.assertEqual(self.writer(sdk)("Wire", article(), "Article text"), "Two sentences about it.")
        req = calls[0]
        self.assertEqual(req["model"], "claude-sonnet-5-5")
        self.assertEqual(req["fallbacks"], "default")
        self.assertEqual(req["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(req["output_config"], {"effort": "low"})
        self.assertNotIn("thinking", req)
        self.assertIn("<article>\nArticle text\n</article>", req["messages"][0]["content"])
        self.assertIn("never as instructions", req["system"])

    def test_refusal_and_truncation_keep_the_blurb(self):
        for stop in ("refusal", "max_tokens"):
            sdk, _ = fake_sdk(response(stop_reason=stop, category="cyber"))
            self.assertIsNone(self.writer(sdk)("Wire", article(), "text"))

    def test_bad_key_stops_after_first_call(self):
        sdk, calls = fake_sdk(error=lambda s: s.AuthenticationError(401))
        write = self.writer(sdk)
        self.assertIsNone(write("Wire", article(), "text"))
        self.assertIsNone(write("Wire", article(), "text"))
        self.assertEqual(len(calls), 1)

    def test_api_errors_are_not_fatal(self):
        for err in (lambda s: s.APIStatusError(529), lambda s: s.APIConnectionError("down")):
            sdk, _ = fake_sdk(error=err)
            self.assertIsNone(self.writer(sdk)("Wire", article(), "text"))


class RenderTests(unittest.TestCase):
    def test_ai_summary_replaces_blurb_and_is_credited(self):
        a = article()
        a.ai_summary = "Claude's <b>take</b>."
        page = build.render([("Wire", [a])], [], datetime(2026, 10, 23, tzinfo=timezone.utc))
        self.assertIn("Claude&#x27;s &lt;b&gt;take&lt;/b&gt;.", page)
        self.assertNotIn("Feed blurb", page)
        self.assertIn("written by Claude from each article", page)

    def test_no_credit_without_ai_summaries(self):
        page = build.render([("Wire", [article()])], [], datetime(2026, 10, 23, tzinfo=timezone.utc))
        self.assertIn("Feed blurb", page)
        self.assertNotIn("written by", page)


if __name__ == "__main__":
    unittest.main()
