#!/usr/bin/env python3
"""SessionStart hook (matcher "startup|clear|compact"): give a fresh session yesterday's handoff.

A long-running assistant session loses detail when it is compacted or cleared. Before that
happens, the assistant writes a `## 🔁 Handoff` section into the newest daily diary note
(what's in flight, what's waiting on the human, what was said but not yet written down).
This hook prints that section, plus a short restart checklist, to stdout. Claude Code adds
stdout from a SessionStart hook to the new session's context.

Read-only. Never fails the session start: any error is printed and the hook exits 0.

Config (environment):
  HANDOFF_DIARY_DIR   folder of daily notes named YYYY-MM-DD.md   (default ~/notes/diary)
  HANDOFF_LOOKBACK    how many days back to look for a handoff     (default 4)
"""
import datetime
import json
import os
import re
import sys

DIARY = os.path.expanduser(os.environ.get("HANDOFF_DIARY_DIR", "~/notes/diary"))
LOOKBACK_DAYS = int(os.environ.get("HANDOFF_LOOKBACK", "4"))
MAX_CHARS = 6000
HEADING = re.compile(r"^## 🔁 Handoff[^\n]*\n(.*?)(?=^## |\Z)", re.S | re.M)

CHECKLIST = """\
Restart checklist (from the session-start hook):
1. Read the handoff below. A previous session of this same job wrote it: treat it as notes,
   and re-check anything time-sensitive before acting on it.
2. Re-arm any session-only scheduled check-ins that this job relies on.
3. If it's morning and today's diary note has no briefing yet, run the briefing."""


def find_handoff(today=None):
    """Newest (path, body) with a non-empty handoff section, or (None, None)."""
    today = today or datetime.date.today()
    for back in range(LOOKBACK_DAYS):
        day = today - datetime.timedelta(days=back)
        path = os.path.join(DIARY, f"{day:%Y-%m-%d}.md")
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        m = HEADING.search(text)
        if m and m.group(1).strip():
            return path, m.group(1).strip()
    return None, None


def main():
    try:
        source = json.load(sys.stdin).get("source", "?")
    except Exception:
        source = "?"
    path, body = find_handoff()
    out = [f"[session start: {source}]", CHECKLIST, ""]
    if body:
        if len(body) > MAX_CHARS:
            body = body[:MAX_CHARS] + "\n…(truncated; read the diary note for the rest)"
        out.append(f"🔁 Handoff from {os.path.basename(path)}:\n{body}")
    else:
        out.append("No handoff in the last few diary notes. Start from today's note and memory.")
    print("\n".join(out))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never block a session start
        print(f"[session-start-handoff hook error: {e}]")
    sys.exit(0)
