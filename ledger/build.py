#!/usr/bin/env python3
"""
Build The Zero-Day Ledger: pull the latest stories from a handful of
cybersecurity news feeds and render them into a static site in dist/.

Standard library only (Python 3.11+), except the anthropic SDK that
summarize.py loads when it writes story summaries.

Usage:
    python3 ledger/build.py              # 4 stories per wire -> dist/
    python3 ledger/build.py -n 3         # 3 stories per wire
    python3 ledger/build.py --no-summaries   # feed blurbs, no Claude calls
"""

import argparse
import html
import json
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

import summarize as ai
from log import alert, summary

FEEDS = {
    "Krebs on Security": "https://krebsonsecurity.com/feed/",
    "The Hacker News": "https://feeds.feedburner.com/TheHackersNews",
    "BleepingComputer": "https://www.bleepingcomputer.com/feed/",
    "Dark Reading": "https://www.darkreading.com/rss.xml",
    "SecurityWeek": "https://feeds.feedburner.com/securityweek",
}

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
KEV_CATALOG = "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"
KEV_WINDOW_DAYS = 30
KEV_FRESH_DAYS = 7
MAX_KEV_BYTES = 20 * 1024 * 1024

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "ledger" / "template.html"
STATIC = ROOT / "static"

USER_AGENT = "Mozilla/5.0 (compatible; ZeroDayLedger/2.0)"
MAX_FEED_BYTES = 5 * 1024 * 1024
FIRST_EDITION = date(2026, 10, 22)

ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"
TAG_RE = re.compile(r"<[^>]+>")
CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}")
CWE_RE = re.compile(r"CWE-(\d+)")
EPOCH = datetime.min.replace(tzinfo=timezone.utc)


@dataclass
class Article:
    title: str
    url: str
    summary: str
    published: datetime | None
    body: str = ""        # full plain text the feed carries, used as summary source
    ai_summary: str = ""  # Claude's summary, when there is one


@dataclass
class Kev:
    cve: str
    name: str
    description: str
    added: date
    due: date | None
    ransomware: bool
    cwes: list[str]
    advisory: str


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


def plain_text(raw):
    return squash(TAG_RE.sub(" ", raw or ""))


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
            body=plain_text(item.findtext(CONTENT_ENCODED) or item.findtext("description")),
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
            body=plain_text(entry.findtext(f"{ATOM}content") or entry.findtext(f"{ATOM}summary")),
        ))

    articles = [a for a in articles if a.title and a.url]
    articles.sort(key=lambda a: a.published or EPOCH, reverse=True)
    return articles


def parse_date_only(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def vendor_advisory(notes):
    """First link in a KEV entry's notes that isn't CISA's or NVD's own."""
    for part in (notes or "").split(";"):
        url = safe_url(part)
        host = urlparse(url).hostname or ""
        if url and not host.endswith(("cisa.gov", "nvd.nist.gov")):
            return url
    return ""


def parse_kev(json_bytes):
    """Parse CISA's Known Exploited Vulnerabilities catalog into Kev entries."""
    entries = []
    for v in json.loads(json_bytes).get("vulnerabilities", []):
        cve = (v.get("cveID") or "").strip()
        added = parse_date_only(v.get("dateAdded"))
        if not CVE_RE.fullmatch(cve) or not added:
            continue
        entries.append(Kev(
            cve=cve,
            name=squash(v.get("vulnerabilityName")) or cve,
            description=summarize(v.get("shortDescription"), max_len=320),
            added=added,
            due=parse_date_only(v.get("dueDate")),
            ransomware=(v.get("knownRansomwareCampaignUse") or "").strip().lower() == "known",
            cwes=[c for c in v.get("cwes") or [] if CWE_RE.fullmatch(c)],
            advisory=vendor_advisory(v.get("notes")),
        ))
    return entries


def pick_kev(entries, today):
    """Choose today's CVE and count the catalog's recent additions.

    The pick rotates through what CISA added in the past week, falling back to
    the past 30 days in a quiet stretch. Rotation is keyed on the date, so a
    rebuild on the same day prints the same CVE.
    """
    recent = [e for e in entries if 0 <= (today - e.added).days <= KEV_WINDOW_DAYS]
    if not recent:
        return None, 0
    fresh = [e for e in recent if (today - e.added).days < KEV_FRESH_DAYS]
    pool = sorted(fresh or recent, key=lambda e: (e.ransomware, e.added, e.cve), reverse=True)
    return pool[today.toordinal() % len(pool)], len(recent)


# --- Fetching ----------------------------------------------------------------

def fetch(url, timeout=15, max_bytes=MAX_FEED_BYTES):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError(f"response is larger than {max_bytes // (1024 * 1024)} MB")
    return body


def todays_kev(today, fetcher=fetch):
    """(Kev, recent count), or (None, 0) if CISA's feed is unavailable."""
    try:
        return pick_kev(parse_kev(fetcher(KEV_URL, max_bytes=MAX_KEV_BYTES)), today)
    except Exception as exc:  # the paper still prints without the bulletin
        alert(f"CISA KEV feed unavailable ({exc}); printing without CVE of the Day.")
        return None, 0


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
            alert(f"Wire down: {name} ({exc})")
            down.append(name)
            continue
        fresh = [a for a in articles if a.url not in seen][:per_wire]
        if not fresh:
            alert(f"Wire down: {name} returned no usable stories")
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
    dek = article.ai_summary or article.summary
    if dek:
        lines.append(f'        <p class="dek">{e(dek)}</p>')
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


def render_kev(kev, recent_count):
    if kev is None:
        return ""
    e = html.escape
    nvd = f"https://nvd.nist.gov/vuln/detail/{kev.cve}"
    # (label, value, is_alarming)
    facts = [("Added to KEV", f"{kev.added:%b %d, %Y}", False)]
    if kev.due:
        facts.append(("Federal deadline", f"{kev.due:%b %d, %Y}", False))
    facts.append(("Ransomware use", "Known" if kev.ransomware else "Not known", kev.ransomware))
    if kev.cwes:
        facts.append(("Weakness", ", ".join(kev.cwes), False))
    alarm_attr = ' class="alarm"'
    fact_html = "\n".join(
        f'        <div><dt>{label}</dt><dd{alarm_attr if alarm else ""}>{e(value)}</dd></div>'
        for label, value, alarm in facts
    )

    links = [f'<a href="{nvd}" target="_blank" rel="noopener noreferrer">NVD entry</a>']
    if kev.advisory:
        links.append(f'<a href="{e(kev.advisory)}" target="_blank" rel="noopener noreferrer">Vendor advisory</a>')
    links.append(f'<a href="{KEV_CATALOG}" target="_blank" rel="noopener noreferrer">CISA catalog</a>')
    noun = "vulnerability" if recent_count == 1 else "vulnerabilities"

    return (
        '    <aside class="bulletin" aria-labelledby="kev-title">\n'
        '      <div class="dispatch-head">\n'
        '        <span class="dispatch-label">CVE of the Day</span>\n'
        '        <span class="bulletin-source">From CISA&rsquo;s Known Exploited Vulnerabilities catalog</span>\n'
        '      </div>\n'
        '      <hr class="dispatch-rule">\n'
        f'      <p class="bulletin-id"><a href="{nvd}" target="_blank" rel="noopener noreferrer">{kev.cve}</a></p>\n'
        f'      <h2 class="bulletin-title" id="kev-title">{e(kev.name)}</h2>\n'
        f'      <p class="dek">{e(kev.description)}</p>\n'
        '      <dl class="bulletin-facts">\n'
        f'{fact_html}\n'
        '      </dl>\n'
        f'      <p class="meta">{" &middot; ".join(links)}</p>\n'
        f'      <p class="meta">One of {recent_count} {noun} CISA confirmed exploited '
        f'in the last {KEV_WINDOW_DAYS} days.</p>\n'
        '    </aside>'
    )


def render(dispatches, down, built_at, kev=None, kev_recent=0):
    total = len(dispatches) + len(down)
    status = f"All {total} wires live" if not down else f"{len(dispatches)} of {total} wires live"
    down_notice = ""
    if down:
        down_notice = f'<p class="down">No word this morning from {html.escape(", ".join(down))}.</p>'
    summary_note = ""
    if any(a.ai_summary for _, articles in dispatches for a in articles):
        summary_note = ('<p>Story summaries written by Claude from each article.<br>'
                        'Follow the headline for the full report.</p>')

    return Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        issue=max(1, (built_at.date() - FIRST_EDITION).days + 1),
        built_iso=built_at.isoformat(timespec="minutes"),
        built_date=f"{built_at:%A, %B} {built_at.day}, {built_at.year}",
        built_time=f"{built_at:%H:%M}",
        wire_count=total,
        wire_status=status,
        down_notice=down_notice,
        summary_note=summary_note,
        kev=render_kev(kev, kev_recent),
        dispatches="\n".join(render_dispatch(i, s, a) for i, (s, a) in enumerate(dispatches, 1)),
    )


def write_site(page, summaries_json, out_dir):
    shutil.copytree(STATIC, out_dir, dirs_exist_ok=True)
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    (out_dir / "summaries.json").write_text(summaries_json, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Build The Zero-Day Ledger.")
    ap.add_argument("-n", "--per-wire", type=int, default=4, help="stories per wire (default 4)")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "dist", help="output folder (default dist/)")
    ap.add_argument("--no-summaries", action="store_true", help="skip Claude summaries, keep feed blurbs")
    args = ap.parse_args()

    print("Pulling the wires...", file=sys.stderr)
    dispatches, down = gather(FEEDS, args.per_wire)
    if not dispatches:
        alert("Every wire is down; not overwriting the last edition.")
        sys.exit(1)

    built_at = datetime.now(timezone.utc)
    kev, kev_recent = todays_kev(built_at.date())

    reused = written = 0
    if not args.no_summaries:
        writer = ai.make_writer()
        if writer is None:
            alert("No ANTHROPIC_API_KEY: reusing published summaries only.")
        reused, written = ai.add_summaries(dispatches, writer, fetch, ai.load_cache(fetch))

    page = render(dispatches, down, built_at, kev, kev_recent)
    write_site(page, ai.cache_document(dispatches), args.out)
    stories = sum(len(a) for _, a in dispatches)
    print(f"Printed {stories} stories from {len(dispatches)} wires to {args.out}"
          f" (CVE of the day: {kev.cve if kev else 'none'};"
          f" summaries: {written} new, {reused} reused)", file=sys.stderr)
    summary(f"### Edition No. {max(1, (built_at.date() - FIRST_EDITION).days + 1)}\n"
            f"- {stories} stories from {len(dispatches)} of {len(FEEDS)} wires\n"
            f"- CVE of the Day: {kev.cve if kev else 'none'}\n"
            f"- Summaries: {written} new, {reused} reused, "
            f"{stories - written - reused} on feed blurbs")


if __name__ == "__main__":
    main()
