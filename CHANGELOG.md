# Changelog

Notable changes to [The Zero-Day Ledger](https://thezerodayledger.com). The
daily editions themselves aren't listed here; this tracks changes to the paper.

To get notified of new versions, watch this repository and choose
**Custom → Releases**.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).

## [1.4.0] - 2026-10-26

### Added
- Keyboard shortcuts: `j` and `k` step through the stories, `o` opens the
  current one, and `?` opens a short guide.
- "How to read the Ledger", a fold-out guide under the date line. It lists
  the shortcuts and explains the NEW stamp, the KEV mark, the story labels
  and where the CVE of the Day comes from. The page still opens on the
  masthead; the guide stays closed until you ask for it.

## [1.3.3] - 2026-10-26

### Security
- The deploy job now uses Wrangler 4.153.0, which brings in undici 7.30.1.
  It fixes two denial-of-service bugs and a Subresource Integrity bypass
  (GHSA-4qv8-2p9j-2685, GHSA-f72v-6w45-q472, GHSA-xjj6-f33q-929c). The
  affected code runs only during deploys, when Wrangler talks to Cloudflare's
  API; nothing on the site itself used it.

## [1.3.2] - 2026-10-23

### Security
- The deploy job installs Wrangler from a lockfile that pins it and every
  package under it by integrity hash, with install scripts disabled.
  Previously Wrangler's own dependencies were resolved fresh from npm in the
  job that holds the Cloudflare token. Dependabot now tracks Wrangler too.

## [1.3.1] - 2026-10-23

### Fixed
- Weekly roundups and digests no longer collect every label that applies to
  one of their items; they now get none.
- Changing the summary prompt now rewrites the summaries already on the page
  instead of leaving them in the old style until they age out.

## [1.3.0] - 2026-10-23

### Added
- Stories can carry up to four labels: **Ransomware**, **Data breach**,
  **Patch available** and **Nation-state**. Claude picks them from that fixed
  list along with the summary, and only when the article states the fact
  outright; many stories get none.

### Changed
- `summaries.json` now stores each story's labels next to its summary.
  Summaries saved before labels existed are written once more to pick them up.

## [1.2.0] - 2026-10-23

### Added
- CVE IDs in story summaries now link to their NVD entries.
- CVEs in CISA's Known Exploited Vulnerabilities catalog carry a red **KEV**
  mark. The mark comes from CISA's catalog, not from the summary, so it only
  appears once CISA has confirmed exploitation.

## [1.1.1] - 2026-10-23

### Fixed
- The footer now credits summaries to Claude rather than naming Claude Sonnet
  5.5. Summaries are requested from Sonnet 5.5, but one that trips a safety
  filter is rerouted to another model, so naming a single model wasn't
  always accurate.

## [1.1.0] - 2026-10-23

### Added
- Stories that weren't on the page at your last visit now carry a **New**
  stamp. The list of stories you've seen stays in your browser and is never
  sent anywhere. Reloading within half an hour keeps the stamps; first visits
  show none.
- This changelog, plus GitHub Releases for each version.

### Security
- The monthly keep-alive workflow now grants write access only to the job that
  needs it, instead of to the whole workflow.

## [1.0.0] - 2026-10-22

First edition.

### Added
- A daily front page of the top stories from five cybersecurity news wires,
  rebuilt every morning at 11:00 UTC and set in typewriter type, with light
  and dark editions.
- **CVE of the Day**: one vulnerability from CISA's Known Exploited
  Vulnerabilities catalog, with its federal patch deadline, known ransomware
  use and links to NVD and the vendor advisory.
- Short story summaries written by Claude, cached so each story is summarized
  only once.
- A watchdog that checks the live site every six hours for uptime, a stale
  edition, an expiring certificate, missing security headers or unexpected
  scripts.

### Security
- Strict Content Security Policy; fonts are self-hosted, and the page loads
  nothing from third parties.
- Cloudflare's injected analytics beacon is blocked, so visitors aren't
  tracked.
- GitHub Actions are pinned to commit SHAs, Python dependencies are
  hash-pinned, and Dependabot keeps both current.
- Signed commits are required on `main`, and CodeQL and OpenSSF Scorecard
  scan the repository.
- `security.txt` and a security policy with private vulnerability reporting.
- DNSSEC, HTTPS everywhere, and a null mail setup so the domain can't be used
  to send spoofed email.

[1.4.0]: https://github.com/rk-secops/zero-day-ledger/compare/v1.3.3...v1.4.0
[1.3.3]: https://github.com/rk-secops/zero-day-ledger/compare/v1.3.2...v1.3.3
[1.3.2]: https://github.com/rk-secops/zero-day-ledger/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/rk-secops/zero-day-ledger/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/rk-secops/zero-day-ledger/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/rk-secops/zero-day-ledger/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/rk-secops/zero-day-ledger/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/rk-secops/zero-day-ledger/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/rk-secops/zero-day-ledger/releases/tag/v1.0.0
