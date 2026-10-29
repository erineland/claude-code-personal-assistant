#!/usr/bin/env python3
"""PreToolUse guard (matcher "Edit|Write") for UNATTENDED runs: notes may only grow at the log.

The nightly job updates a folder of curated notes from new messages. Nobody is watching, so the
model may add a dated entry under the note's log heading and bump `updated:`, and nothing else.
Rather than trust an instruction, this hook *simulates* the edit and refuses it if the result
would:
  - change anything above the log heading (the curated sections),
  - remove or alter any existing log text,
  - create a new note,
  - touch any file outside the allowed folders,
  - use any tool other than Edit or Write.

It fails CLOSED: if the guard itself errors, the edit is refused.

Paths are resolved (symlinks, `..`) and compared case-insensitively, because a case-insensitive
filesystem would otherwise let `NOTES/../secrets.md` or `notes/X.MD` slip past a string check.

Config (environment):
  GUARD_NOTES_DIR    folder of person/topic notes, edited log-only   (required)
  GUARD_EXTRA_DIRS   os.pathsep-separated folders writable freely (e.g. the digest folder)
  GUARD_LOG_HEADING  the heading that starts the log                  (default "## 🗓 Log")
"""
import json
import os
import pathlib
import re
import sys

LOG_HEADING = "\n" + os.environ.get("GUARD_LOG_HEADING", "## 🗓 Log")


def split(text):
    """(curated head, log) at the log heading. No heading means the whole note is head."""
    i = text.find(LOG_HEADING)
    return (text, "") if i < 0 else (text[:i], text[i:])


def head_key(head):
    # Bumping `updated:` in the frontmatter is the one allowed change above the log.
    return re.sub(r"(?m)^updated:.*$", "", head)


def problems_with(before, after):
    bh, bl = split(before)
    ah, al = split(after)
    found = []
    if head_key(bh) != head_key(ah):
        found.append("it changes the note above the log")
    if bl:
        cut = bl.find("\n### ")
        intro, entries = (bl, "") if cut < 0 else (bl[:cut], bl[cut:])
        # New entries go at the top of the log (newest first): the old ones must survive intact.
        if not al.startswith(intro) or entries not in al:
            found.append("it removes or alters existing log text")
    return found


def _real(p):
    return os.path.realpath(os.path.expanduser(p)).lower()


def classify(raw, notes_dir, extra_dirs):
    """'note' for a direct child .md of notes_dir, 'extra' for anything under extra_dirs, else None."""
    low = _real(raw)
    notes = _real(notes_dir) + os.sep
    if low.startswith(notes) and os.sep not in low[len(notes):] and low.endswith(".md"):
        return "note"
    if any(low.startswith(_real(d) + os.sep) for d in extra_dirs if d):
        return "extra"
    return None


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))


def check(event, notes_dir, extra_dirs):
    tool, args = event.get("tool_name"), event.get("tool_input") or {}
    # Allowlist: only Edit and Write are simulated. The "Edit|Write" matcher also catches
    # MultiEdit and NotebookEdit, which have no old_string and would otherwise pass as a no-op.
    if tool not in ("Edit", "Write"):
        return deny(f"Refused: unattended runs may only use Edit or Write, not {tool}.")
    raw = str(args.get("file_path", ""))
    if ".." in pathlib.PurePath(raw).parts:
        return deny("Refused: the path contains '..'. Use the note's plain path.")
    kind = classify(raw, notes_dir, extra_dirs)
    if kind is None:
        return deny("Refused: unattended runs may only edit the notes folder and the digest.")
    if kind == "extra":
        return None
    path = pathlib.Path(os.path.realpath(os.path.expanduser(raw)))
    if not path.exists():
        return deny(f"{path.name} doesn't exist, and unattended runs never create notes. "
                    "Flag it in the digest instead.")
    before = path.read_text(encoding="utf-8")
    if tool == "Write":
        after = args.get("content", "")
    else:
        old, new = args.get("old_string", ""), args.get("new_string", "")
        if old not in before:
            return None  # the Edit tool fails on its own
        after = before.replace(old, new) if args.get("replace_all") else before.replace(old, new, 1)
    problems = problems_with(before, after)
    if problems:
        return deny(f"Refused: {'; '.join(problems)}. Unattended runs may only add log entries and "
                    "bump `updated:`. Put proposed section changes in the digest instead.")
    return None


def main():
    notes_dir = os.environ.get("GUARD_NOTES_DIR")
    if not notes_dir:
        return deny("Refused: GUARD_NOTES_DIR isn't set, so the guard can't tell what's allowed.")
    extra = os.environ.get("GUARD_EXTRA_DIRS", "").split(os.pathsep)
    return check(json.load(sys.stdin), notes_dir, extra)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail closed
        deny(f"Refused: the safety check couldn't run ({type(e).__name__}), so no edits are allowed.")
    sys.exit(0)
