#!/usr/bin/env python3
"""SessionEnd hook: write a one-page, searchable digest of the session into a notes folder.

A raw transcript is too long to re-read. The digest is an index instead, built without an LLM:
for each day the session covered, it lists
  - the human's own prompts (one line each, timestamped),
  - the notes the session read or edited (as wiki links),
  - the skills it used.
Decisions themselves live in the daily diary; the digest is how you find which session made them.

Prompts can contain secrets, so a small redaction pass runs first. For full transcript export
with thorough redaction (exact-value, hashed and pattern matching), see the session-export hook
in https://github.com/erineland/claude-code-guardrails.

Config (environment):
  DIGEST_OUT_DIR     where digests go                       (default ~/notes/sessions)
  DIGEST_NOTES_ROOT  the notes vault, to spot touched notes (default ~/notes)
  DIGEST_DRY_RUN=1   print the digest instead of writing it
"""
import datetime
import json
import os
import re
import sys

OUT_DIR = os.path.expanduser(os.environ.get("DIGEST_OUT_DIR", "~/notes/sessions"))
NOTES_ROOT = os.path.realpath(os.path.expanduser(os.environ.get("DIGEST_NOTES_ROOT", "~/notes")))
DRY_RUN = os.environ.get("DIGEST_DRY_RUN") == "1"

SKIP_PREFIXES = ("<local-command", "<command-", "<task-notification", "<system-reminder",
                 "[Request interrupted", "<bash-input", "<bash-stdout", "<bash-stderr")
REMINDER_BLOCK = re.compile(r"<system-reminder[\s\S]*?</system-reminder>")

REDACT = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?i)\b(?:password|passphrase|api[ _-]?key|token|secret)\b\s*(?:is|=|:)\s*\S{6,}"),
    re.compile(r"\b\d(?:[ -]?\d){12,18}\b"),  # card-number shaped
]


def redact(text):
    for pattern in REDACT:
        text = pattern.sub("[REDACTED]", text)
    return text


def local_day_time(ts):
    try:
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    except Exception:
        return "unknown", "--:--"


def prompt_text(record):
    if record.get("isMeta"):
        return ""
    content = record.get("message", {}).get("content")
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return ""
        content = "\n".join(b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str):
        return ""
    text = REMINDER_BLOCK.sub("", content).strip()
    return "" if not text or text.startswith(SKIP_PREFIXES) else text


def note_rel(path):
    real = os.path.realpath(os.path.expanduser(str(path)))
    if real.startswith(NOTES_ROOT + os.sep) and real.endswith(".md"):
        return real[len(NOTES_ROOT) + 1:]
    return None


def collect(lines):
    days = {}

    def day(d):
        return days.setdefault(d, {"prompts": [], "edited": set(), "read": set(), "skills": set()})

    for line in lines:
        try:
            record = json.loads(line)
        except Exception:
            continue
        if record.get("type") not in ("user", "assistant"):
            continue
        d, t = local_day_time(record.get("timestamp", ""))
        if record["type"] == "user":
            text = prompt_text(record)
            if text:
                one = re.sub(r"\s+", " ", redact(text))
                one = one if len(one) <= 220 else one[:217] + "…"
                day(d)["prompts"].append(f"- **{t}** {one}")
            continue
        for block in record.get("message", {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name, inp = block.get("name", ""), block.get("input") or {}
            if name == "Skill" and inp.get("skill"):
                day(d)["skills"].add(inp["skill"])
            elif name in ("Write", "Edit", "Read"):
                rel = note_rel(inp.get("file_path", ""))
                if rel:
                    day(d)["read" if name == "Read" else "edited"].add(rel)
    days.pop("unknown", None)
    return days


def render(days, session_id):
    out = [f"---\nsession: {session_id}\ndays: [{', '.join(sorted(days))}]\n---\n",
           f"# Session digest {session_id[:8]}\n"]
    link = lambda rel: f"[[{rel[:-3]}|{os.path.basename(rel)[:-3]}]]"
    for d in sorted(days):
        v = days[d]
        out.append(f"## {d}\n")
        if v["prompts"]:
            out.append("**What I asked**\n" + "\n".join(v["prompts"]) + "\n")
        if v["edited"]:
            out.append("**Notes edited:** " + ", ".join(link(r) for r in sorted(v["edited"])) + "\n")
        if v["read"] - v["edited"]:
            out.append("**Notes read:** " + ", ".join(link(r) for r in sorted(v["read"] - v["edited"])) + "\n")
        if v["skills"]:
            out.append("**Skills:** " + ", ".join(sorted(v["skills"])) + "\n")
    return "\n".join(out)


def main():
    event = json.load(sys.stdin)
    path, session_id = event.get("transcript_path"), event.get("session_id", "unknown")
    if not path or not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        days = collect(f)
    if not any(v["prompts"] for v in days.values()):
        return  # nothing the human said: not worth a digest
    text = render(days, session_id)
    if DRY_RUN:
        print(text)
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    first = min(days)
    with open(os.path.join(OUT_DIR, f"{first} {session_id[:8]}.md"), "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never block a session end
        print(f"[session-end-digest hook error: {e}]", file=sys.stderr)
    sys.exit(0)
