#!/usr/bin/env python3
"""PreToolUse guard for a browser-automation MCP server: anything outward-facing asks first.

Matcher (Playwright MCP naming, adjust to your server):
  mcp__playwright__browser_(click|type|press_key|fill_form|select_option|file_upload|evaluate|handle_dialog)

Reading pages is free. The model gets a forced permission prompt when an action could change
something in the world:
  - a click whose label sounds outward-facing (submit, pay, book, delete, sign in, ...),
  - a click with NO label (a bare element ref would otherwise slip past any word check),
  - typing that submits, or pressing Enter,
  - filling a form that has a password or payment field,
  - a page script that clicks, posts, or reads cookies or storage,
  - any file upload, or accepting a dialog.

It returns "ask", never "deny": the human stays the decision-maker. It fails CLOSED: an
unreadable payload is asked about too.
"""
import json
import re
import sys

RISKY = re.compile(
    r"\b(submit|send|confirm|book(?:ing)?|pay(?:ment)?|place order|purchase|checkout|check out|"
    r"buy|reserve|order|donate|subscribe|transfer|forward|delete|remove|save|"
    r"sign[ -]?in|log[ -]?in|allow|accept|approve|authori[sz]e)\b", re.I)
SECRET_FIELD = re.compile(r"(?i)password|passcode|card|cvc|cvv|security code|sort ?code|"
                          r"account (?:no|number)|iban|expiry")
SCRIPT_RISK = re.compile(r"\.click\s*\(|\.submit\s*\(|\bPOST\b|sendBeacon|XMLHttpRequest|fetch\s*\(|"
                         r"document\.cookie|localStorage|sessionStorage|indexedDB", re.I)
ENTER_KEYS = {"enter", "numpadenter", "return"}


def verdict(tool, ti):
    """A reason string if this action needs a human yes, else None."""
    action = tool.rsplit("__", 1)[-1]
    label = str(ti.get("element") or "")
    if action == "browser_click":
        if not label.strip():
            return "a click on an element with no label"
        if RISKY.search(label):
            return f"a click on '{label}'"
    elif action == "browser_type":
        if ti.get("submit"):
            return f"typing into '{label}' and submitting"
        if SECRET_FIELD.search(label):
            return f"typing into a sensitive field ('{label}')"
    elif action == "browser_press_key":
        if str(ti.get("key", "")).lower() in ENTER_KEYS:
            return "pressing Enter (it usually submits)"
    elif action in ("browser_fill_form", "browser_select_option"):
        if SECRET_FIELD.search(json.dumps(ti)):
            return "filling a form with a password or payment field"
    elif action == "browser_evaluate":
        if SCRIPT_RISK.search(str(ti.get("function", ""))):
            return "a page script that clicks, posts or reads storage"
    elif action == "browser_file_upload":
        return "uploading a file"
    elif action == "browser_handle_dialog":
        if ti.get("accept"):
            return "accepting a browser dialog"
    return None


def ask(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": f"BROWSER GUARD: {reason}. Check it before it goes ahead."}}))


def main():
    try:
        payload = json.load(sys.stdin)
        tool = payload.get("tool_name", "")
        ti = payload.get("tool_input") or {}
        if not isinstance(tool, str) or not isinstance(ti, dict):
            raise ValueError("bad payload")
    except Exception:
        return ask("couldn't read this browser action")
    reason = verdict(tool, ti)
    if reason:
        ask(reason)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        ask("the guard hit an error")
    sys.exit(0)
