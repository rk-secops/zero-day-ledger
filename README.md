# The Zero-Day Ledger

A daily cybersecurity front page, set in type. Every morning a GitHub Action pulls the
latest stories from five news wires (Krebs on Security, The Hacker News,
BleepingComputer, Dark Reading, SecurityWeek), renders them into a static
page, and deploys it to Cloudflare (Workers static assets).

## Layout

```
ledger/build.py       fetch feeds -> parse -> render -> dist/
ledger/template.html  page skeleton ($placeholders filled by build.py)
static/                copied into dist/ as-is: CSS, typewriter JS, favicon,
                       _headers (security headers + caching)
tests/                 offline unit tests (no network)
wrangler.jsonc         Cloudflare config: serve dist/ as static assets
.github/workflows/     test, then build and deploy on a daily schedule
```

## Design notes

- **Rendered on the server, escaped.** Headlines are plain HTML built with
  `html.escape`, so the page works without JavaScript and nothing from a feed
  can inject markup. Only `http(s)` links are kept.
- **Strict CSP.** No inline script or style, so the Content-Security-Policy in
  `static/_headers` can be `script-src 'self'`.
- **CVE of the Day.** A boxed bulletin from CISA's Known Exploited
  Vulnerabilities catalog. It rotates daily through the past week's
  additions (past 30 days if CISA has been quiet); if the feed is down the
  bulletin is simply left out.
- **Fails safe.** A dead wire is skipped and noted in the colophon. If every
  wire is down, the build fails and the last edition stays live.
- **Standard library only.** Python 3.11+, nothing to install.

## Local preview

```
python3 -m unittest discover -s tests
python3 ledger/build.py
python3 -m http.server -d dist 8000     # then open http://localhost:8000
```

## Deploying

The site is served at **https://thezerodayledger.com** (set in `wrangler.jsonc`).

1. Push this folder to a new GitHub repo (branch `main`).
2. Make sure `thezerodayledger.com` is an active zone in your Cloudflare
   account (automatic if bought through Cloudflare Registrar; otherwise
   **Add a domain** and point the registrar's nameservers at Cloudflare).
3. Cloudflare dashboard -> **My Profile -> API Tokens -> Create Token** ->
   template **Edit Cloudflare Workers**. Under **Zone Resources** include
   `thezerodayledger.com`, and add the permission **Zone -> DNS -> Edit** so
   the deploy can attach the custom domain. Copy the token.
4. Copy your **Account ID** (dashboard home -> account menu, or the right
   sidebar of any zone / Workers overview).
5. GitHub repo -> **Settings -> Secrets and variables -> Actions** -> add
   `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.
6. **Actions -> Press run -> Run workflow** for the first edition. The first
   deploy creates the `zero-day-ledger` Worker, attaches the domain, and
   issues its certificate (can take a few minutes on the very first run).
7. Optional: send `www.` to the apex with **Rules -> Redirect Rules ->
   Redirect from WWW to root** (needs a proxied `www` DNS record).

You can also deploy by hand: `python3 ledger/build.py && npx wrangler deploy`.

Change the time with the `cron:` line in `.github/workflows/press.yml`, and the
wires with `FEEDS` in `ledger/build.py`.
