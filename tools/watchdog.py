#!/usr/bin/env python3
"""
Watchdog for the live Zero-Day Ledger: checks that what visitors actually get
still matches what this repo deploys. Any problem makes it exit 1, so the
scheduled GitHub Actions run fails and GitHub emails the owner.

Checks: security headers (expected values come from static/_headers), page
integrity (masthead present, only our own script, no iframes), edition
freshness, HTTP->HTTPS redirect, TLS certificate lifetime, security.txt
expiry, and that summaries.json is valid.

Standard library only. Usage: python3 tools/watchdog.py
"""

import json
import re
import socket
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOST = "thezerodayledger.com"
SITE = f"https://{HOST}"
HEADERS_FILE = Path(__file__).resolve().parent.parent / "static" / "_headers"
USER_AGENT = "ZeroDayLedger-Watchdog/1.0"

MAX_EDITION_AGE = timedelta(hours=36)  # daily press run plus slack for one retry
MIN_STORIES = 5
CERT_MIN_DAYS = 14
SECURITY_TXT_MIN_DAYS = 30
ALLOWED_SCRIPTS = {"typewriter.js", "fresh.js", "keys.js"}


# --- Fetching ----------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get(url, follow_redirects=True):
    """(status, headers, body); HTTP errors are returned, not raised."""
    handlers = [] if follow_redirects else [_NoRedirect]
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    try:
        with urllib.request.build_opener(*handlers).open(req, timeout=20) as resp:
            return resp.status, resp.headers, resp.read(2_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, b""


def cert_expiry(host):
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection((host, 443), timeout=20) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            not_after = tls.getpeercert()["notAfter"]
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), timezone.utc)


# --- Checks (pure functions, so they can be tested offline) --------------------

def expected_headers(text):
    """Header name -> value from the "/*" block of a Cloudflare _headers file."""
    expected, in_global = {}, False
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():
            in_global = line.strip() == "/*"
        elif in_global:
            name, _, value = line.strip().partition(":")
            expected[name.strip().lower()] = value.strip()
    return expected


def check_headers(headers, expected):
    problems = []
    for name, value in expected.items():
        actual = headers.get(name)
        if actual is None:
            problems.append(f"header {name} is missing")
        elif actual.strip() != value:
            problems.append(f"header {name} changed: {actual.strip()!r}")
    return problems


def check_page(body, now):
    page = body.decode("utf-8", errors="replace")
    problems = []
    if "Zero-Day</span> Ledger</h1>" not in page:
        problems.append("masthead not found (page replaced or broken?)")

    for tag in re.findall(r"<script\b[^>]*>", page, flags=re.I):
        src = re.search(r'\bsrc="([^"]*)"', tag)
        if not src or src.group(1) not in ALLOWED_SCRIPTS:
            problems.append(f"unexpected script tag: {tag[:120]}")
    if re.search(r"<iframe\b", page, flags=re.I):
        problems.append("page contains an iframe")

    stories = len(re.findall(r'<article class="article">', page))
    if stories < MIN_STORIES:
        problems.append(f"only {stories} stories on the page")

    edition = re.search(r'<div class="dateline">\s*<time datetime="([^"]+)"', page)
    if not edition:
        problems.append("edition date not found")
    else:
        built = datetime.fromisoformat(edition.group(1))
        if now - built > MAX_EDITION_AGE:
            problems.append(f"edition is stale: built {edition.group(1)} (press run failing?)")
    return problems


def check_redirect(status, headers):
    location = headers.get("Location", "") if headers else ""
    if status not in (301, 308) or not location.startswith(f"https://{HOST}"):
        return [f"http:// did not redirect to https (status {status}, Location {location!r})"]
    return []


def check_security_txt(status, body, now):
    if status != 200:
        return [f"security.txt returned {status}"]
    match = re.search(r"^Expires:\s*(\S+)", body.decode("utf-8", errors="replace"), flags=re.M)
    if not match:
        return ["security.txt has no Expires field"]
    left = datetime.fromisoformat(match.group(1)) - now
    if left < timedelta(days=SECURITY_TXT_MIN_DAYS):
        return [f"security.txt expires in {left.days} days: renew it (and rotate API keys)"]
    return []


def check_summaries(status, body):
    if status != 200:
        return [f"summaries.json returned {status}"]
    try:
        data = json.loads(body)
    except ValueError:
        return ["summaries.json is not valid JSON"]
    if not isinstance(data, dict) or not isinstance(data.get("summaries"), dict):
        return ["summaries.json has an unexpected shape"]
    return []


def check_cert(expires, now):
    left = expires - now
    if left < timedelta(days=CERT_MIN_DAYS):
        return [f"TLS certificate expires in {left.days} days ({expires:%Y-%m-%d})"]
    return []


# --- Main --------------------------------------------------------------------

def run_checks():
    now = datetime.now(timezone.utc)
    results = {}

    def attempt(name, fn):
        try:
            results[name] = fn()
        except Exception as exc:  # an unreachable site is itself a finding
            results[name] = [f"check failed: {exc}"]

    def page():
        status, headers, body = get(f"{SITE}/")
        if status != 200:
            return [f"home page returned {status}"]
        return check_headers(headers, expected_headers(HEADERS_FILE.read_text())) + check_page(body, now)

    attempt("home page", page)
    attempt("https redirect", lambda: check_redirect(*get(f"http://{HOST}/", follow_redirects=False)[:2]))
    attempt("security.txt", lambda: check_security_txt(*_status_body(f"{SITE}/.well-known/security.txt"), now))
    attempt("summaries.json", lambda: check_summaries(*_status_body(f"{SITE}/summaries.json")))
    attempt("tls certificate", lambda: check_cert(cert_expiry(HOST), now))
    return results


def _status_body(url):
    status, _, body = get(url)
    return status, body


def main():
    results = run_checks()
    failed = False
    for name, problems in results.items():
        print(f"{'FAIL' if problems else ' ok '}  {name}")
        for problem in problems:
            failed = True
            print(f"      - {problem}")
            print(f"::error title=Watchdog: {name}::{problem}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
