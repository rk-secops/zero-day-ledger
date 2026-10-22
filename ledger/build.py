#!/usr/bin/env python3
"""
Build The Zero-Day Ledger: pull the latest stories from a handful of
cybersecurity news feeds and render them into a static site in dist/.

Standard library only (Python 3.11+).

Usage:
    python3 ledger/build.py              # 4 stories per wire -> dist/
    python3 ledger/build.py -n 3         # 3 stories per wire
"""

import argparse
import html
import re
import shutil
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from string import Template
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

FEEDS = {
    "Krebs on Security": "https://krebsonsecurity.com/feed/",
    "The Hacker News": "https://feeds.feedburner.com/TheHackersNews",
    "BleepingComputer": "https://www.bleepingcomputer.com/feed/",
    "Dark Reading": "https://www.darkreading.com/rss.xml",
    "SecurityWeek": "https://feeds.feedburner.com/securityweek",
}

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "ledger" / "template.html"
STATIC = ROOT / "static"

USER_AGENT = "Mozilla/5.0 (compatible; ZeroDayLedger/2.0)"
MAX_FEED_BYTES = 5 * 1024 * 1024
FIRST_EDITION = date(2026, 10, 22)

ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"
TAG_RE = re.compile(r"<[^>]+>")
EPOCH = datetime.min.replace(tzinfo=timezone.utc)


@dataclass
class Article:
    title: str
    url: str
    summary: str
    published: datetime | None


# --- Parsing -----------------------------------------------------------------

def squash(text):
    """Unescape entities and collapse whitespace. Keeps literal '<' intact."""
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def summarize(raw, max_len=220):
    """Turn an HTML description into a short plain-text dek."""
    text = squash(TAG_RE.sub(" ", raw or ""))
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "…"
    return text


def safe_url(raw):
    """Only http(s) links make it onto the page (no javascript:, data:, ...)."""
    raw = (raw or "").strip()
    return raw if urlparse(raw).scheme in ("http", "https") else ""


def parse_date(raw):
    """RFC 822 (RSS) or ISO 8601 (Atom), always returned timezone-aware."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_feed(xml_bytes):
    """Parse an RSS 2.0 or Atom feed into Articles, newest first."""
    root = ET.fromstring(xml_bytes)
    articles = []

    for item in root.iter("item"):
        articles.append(Article(
            title=squash(item.findtext("title")),
            url=safe_url(item.findtext("link")),
            summary=summarize(item.findtext("description") or item.findtext(CONTENT_ENCODED)),
            published=parse_date(item.findtext("pubDate")),
        ))

    for entry in root.iter(f"{ATOM}entry"):
        link = next(
            (l.get("href") for l in entry.findall(f"{ATOM}link")
             if l.get("rel", "alternate") == "alternate"),
            "",
        )
        articles.append(Article(
            title=squash(entry.findtext(f"{ATOM}title")),
            url=safe_url(link),
            summary=summarize(entry.findtext(f"{ATOM}summary") or entry.findtext(f"{ATOM}content")),
            published=parse_date(entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated")),
        ))

    articles = [a for a in articles if a.title and a.url]
    articles.sort(key=lambda a: a.published or EPOCH, reverse=True)
    return articles


# --- Fetching ----------------------------------------------------------------

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(MAX_FEED_BYTES + 1)
    if len(body) > MAX_FEED_BYTES:
        raise ValueError("feed is larger than 5 MB")
    return body


def gather(feeds, per_wire, fetcher=fetch):
    """Fetch every feed in parallel.

    Returns (dispatches, down): dispatches is [(source, [Article])] in feed
    order, down is the list of sources that failed or had nothing new.
    A story syndicated on two wires only appears under the first one.
    """
    with ThreadPoolExecutor(max_workers=len(feeds)) as pool:
        futures = {name: pool.submit(lambda u: parse_feed(fetcher(u)), url)
                   for name, url in feeds.items()}

    dispatches, down, seen = [], [], set()
    for name, future in futures.items():
        try:
            articles = future.result()
        except Exception as exc:  # one dead wire shouldn't stop the press
            print(f"[warn] {name}: {exc}", file=sys.stderr)
            down.append(name)
            continue
        fresh = [a for a in articles if a.url not in seen][:per_wire]
        if not fresh:
            print(f"[warn] {name}: no usable stories", file=sys.stderr)
            down.append(name)
            continue
        seen.update(a.url for a in fresh)
        dispatches.append((name, fresh))
    return dispatches, down


# --- Rendering ---------------------------------------------------------------

def render_article(article):
    e = html.escape
    lines = [
        '      <article class="article">',
        f'        <h3 class="headline"><a href="{e(article.url)}" target="_blank" '
        f'rel="noopener noreferrer">{e(article.title)}</a></h3>',
    ]
    if article.summary:
        lines.append(f'        <p class="dek">{e(article.summary)}</p>')
    if article.published:
        lines.append(f'        <p class="meta"><time datetime="{article.published.isoformat()}">'
                     f'{article.published:%b %d, %Y}</time></p>')
    lines.append("      </article>")
    return "\n".join(lines)


def render_dispatch(number, source, articles):
    body = "\n".join(render_article(a) for a in articles)
    return (
        f'    <section class="dispatch" aria-labelledby="wire-{number}">\n'
        f'      <div class="dispatch-head">\n'
        f'        <span class="dispatch-label">Dispatch {number:02d}</span>\n'
        f'        <h2 class="dispatch-source" id="wire-{number}">{html.escape(source)}</h2>\n'
        f'      </div>\n'
        f'      <hr class="dispatch-rule">\n'
        f'{body}\n'
        f'    </section>'
    )


def render(dispatches, down, built_at):
    total = len(dispatches) + len(down)
    status = f"All {total} wires live" if not down else f"{len(dispatches)} of {total} wires live"
    down_notice = ""
    if down:
        down_notice = f'<p class="down">No word this morning from {html.escape(", ".join(down))}.</p>'

    return Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        issue=max(1, (built_at.date() - FIRST_EDITION).days + 1),
        built_iso=built_at.isoformat(timespec="minutes"),
        built_date=f"{built_at:%A, %B} {built_at.day}, {built_at.year}",
        built_time=f"{built_at:%H:%M}",
        wire_count=total,
        wire_status=status,
        down_notice=down_notice,
        dispatches="\n".join(render_dispatch(i, s, a) for i, (s, a) in enumerate(dispatches, 1)),
    )


def write_site(page, out_dir):
    shutil.copytree(STATIC, out_dir, dirs_exist_ok=True)
    (out_dir / "index.html").write_text(page, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Build The Zero-Day Ledger.")
    ap.add_argument("-n", "--per-wire", type=int, default=4, help="stories per wire (default 4)")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "dist", help="output folder (default dist/)")
    args = ap.parse_args()

    print("Pulling the wires...", file=sys.stderr)
    dispatches, down = gather(FEEDS, args.per_wire)
    if not dispatches:
        print("Every wire is down; not overwriting the last edition.", file=sys.stderr)
        sys.exit(1)

    write_site(render(dispatches, down, datetime.now(timezone.utc)), args.out)
    stories = sum(len(a) for _, a in dispatches)
    print(f"Printed {stories} stories from {len(dispatches)} wires to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
