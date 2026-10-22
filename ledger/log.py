"""
Build log helpers.

warn() is for routine trouble that only needs a log line (one site blocking a
fetch). alert() is for trouble a person should look at (a dead wire, a rejected
API key): in GitHub Actions it becomes a warning annotation on the run page and
in the job summary; anywhere else it is a plain stderr line like warn().
"""

import os
import sys


def in_actions():
    return os.environ.get("GITHUB_ACTIONS") == "true"


def warn(message):
    print(f"[warn] {message}", file=sys.stderr)


def alert(message):
    if in_actions():
        # Workflow commands are read from stdout; %, CR and LF must be escaped.
        escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::warning title=Zero-Day Ledger::{escaped}", flush=True)
    else:
        print(f"[alert] {message}", file=sys.stderr)


def summary(markdown):
    """Append to the Actions job summary; a no-op outside Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(markdown.rstrip() + "\n")
