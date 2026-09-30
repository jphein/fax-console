#!/usr/bin/env python3
"""Render Bob Shell's stream-json on a terminal so a person can watch Bob work.

  bob run --format stream-json ... | tee run.jsonl | scripts/bob-watch.py

The tmux window this runs in stays open after the run, so nothing a tool printed is shown: a
tool result shows only its length (an `env` dump would otherwise leave the key in scrollback),
and the API key is masked in everything that is shown.
"""
import json
import os
import re
import shutil
import sys
import textwrap

W = max(40, min(100, shutil.get_terminal_size((80, 20)).columns - 2))
G, Y, R, D, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"
KEY = os.environ.get("BOB_API_KEY", "")


def safe(s):
    return s.replace(KEY, "***") if len(KEY) >= 8 else s


def short(v, n=W - 12):
    s = v if isinstance(v, str) else json.dumps(v)
    s = safe(" ".join(s.split()))
    return s if len(s) <= n else s[: n - 1] + "…"


# A pytest summary line, e.g. "3 failed, 186 passed in 1.98s", optionally inside ===== rules. Only the
# counts, the fixed outcome words and the duration are shown, so nothing else a tool printed reaches the
# screen.
# ASCII digits only, and bounded: a count has at most 5 digits and a duration at most 4 (plus 2 decimals),
# so a phone-shaped number in a tool's output can never pass as a count or a duration (Lucid, on #36).
_OUTCOME = r"[0-9]{1,5} (?:failed|passed|errors?|skipped|xfailed|xpassed|deselected|warnings?)"
FAILING = re.compile(r"[0-9]{1,5} (?:failed|errors?)\b", re.ASCII)
_DURATION = r"[0-9]{1,4}(?:\.[0-9]{1,2})?"
SUMMARY = re.compile(rf"^=*\s*({_OUTCOME}(?:, {_OUTCOME})*) in ({_DURATION})s\b.*$", re.ASCII)


def test_summary(text):
    """The last pytest summary in a tool's output, rebuilt from its parts, or None."""
    found = None
    for line in str(text).splitlines():
        m = SUMMARY.match(line.strip())
        if m:
            found = f"{m.group(1)} in {m.group(2)}s"
    return found


def summary_line(text):
    s = test_summary(text)
    if s is None:
        return None
    colour = R if FAILING.search(s) else G
    return f"{colour}  ▣ tests: {safe(s)}{X}"


# A failed tool's message is never shown: it can hold anything the command printed (another key, a home
# path; the Oracle, on #36). It is shown as fixed words: the exit code, one phrase from these lists, and a
# test summary. A phrase from the first list counts only where the message starts (the guard's and Bob's
# own tool errors). One from the second counts only in the command's stderr, so a test that prints
# "Permission denied" to stdout is not misread.
EXIT = re.compile(r"^Error from tool [a-z_]{1,40}: Exit code: ([0-9]{1,3})\b", re.ASCII)
LEADING_WORDS = (
    ("command refused:", "the guard refused the command"),
    ("path refused:", "the guard refused the path"),
    ("write refused:", "the guard refused the write"),
    ("File does not exist", "file does not exist"),
    ("No matches found", "no matches"),
    ("Invalid range format", "invalid range"),
)
STDERR_WORDS = (
    ("Read-only file system", "read-only file system"),
    ("Operation not permitted", "operation not permitted"),
    ("Permission denied", "permission denied"),
    ("No such file or directory", "no such file or directory"),
)


def error_line(msg):
    """The red line for a failed tool: fixed words only, never the message itself."""
    text = msg if isinstance(msg, str) else json.dumps(msg)
    code = EXIT.match(text)
    words = next((shown for marker, shown in LEADING_WORDS if text.startswith(marker)), None)
    if code and words is None and "Stderr:" in text:
        stderr = text.split("Stderr:", 1)[1]
        words = next((shown for marker, shown in STDERR_WORDS if marker in stderr), None)
    parts = [p for p in (f"exit code {code.group(1)}" if code else None, words) if p]
    return f"{R}  ✗ {' · '.join(parts) if parts else 'failed'} ({len(text)} characters){X}"


def main():
    buf = ""
    for line in sys.stdin:
        try:
            buf = render(line, buf)
        except Exception as ex:  # noqa: BLE001 -- the watcher is a view; it must never stop the run
            print(f"{D}(an event this viewer could not show: {type(ex).__name__}){X}")
    if buf.strip():
        print(G + textwrap.fill(safe(buf), W) + X)


def render(line, buf):
    """Show one stream event; returns the assistant text still waiting for its newline."""
    try:
        e = json.loads(line)
    except ValueError:
        print(D + safe(line.rstrip()) + X)
        return buf
    t = e.get("type")
    if t == "message" and e.get("role") == "assistant":
        buf += str(e.get("content", ""))
        while "\n" in buf:
            head, buf = buf.split("\n", 1)
            print(G + textwrap.fill(safe(head), W) + X if head.strip() else "")
        return buf
    if buf.strip():
        print(G + textwrap.fill(safe(buf), W) + X)
    if t == "tool_use":
        p = e.get("parameters") or {}
        arg = p.get("command") or p.get("path") or p.get("pattern") or p
        print(f"{Y}▶ {e.get('tool_name')}{X} {short(arg)}")
    elif t == "tool_result":
        if e.get("status") == "success":
            out = e.get("output", "")
            print(f"{D}  ✓ {len(out if isinstance(out, str) else json.dumps(out))} characters of output{X}")
            out_summary = summary_line(out if isinstance(out, str) else json.dumps(out))
        else:
            err = e.get("error")
            msg = err.get("message", err) if isinstance(err, dict) else err
            print(error_line(msg))
            out_summary = summary_line(msg if isinstance(msg, str) else json.dumps(msg))
        if out_summary:
            print(out_summary)
    elif t == "result":
        s = e.get("stats") or {}
        print(f"{B}■ {e.get('status')} · cost {s.get('session_costs')} · {s.get('tool_calls')} tool calls · "
              f"{round((s.get('duration_ms') or 0) / 1000)}s · task {s.get('task_id')}{X}")
    return ""

if __name__ == "__main__":
    main()
