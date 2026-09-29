#!/usr/bin/env python3
"""Render Bob Shell's stream-json on a terminal so a person can watch Bob work.

  bob run --format stream-json ... | tee run.jsonl | scripts/bob-watch.py

The tmux window this runs in stays open after the run, so nothing a tool printed is shown: a
tool result shows only its length (an `env` dump would otherwise leave the key in scrollback),
and the API key is masked in everything that is shown.
"""
import json
import os
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
        else:
            err = e.get("error")
            print(f"{R}  ✗ {short(err.get('message', err) if isinstance(err, dict) else err)}{X}")
    elif t == "result":
        s = e.get("stats") or {}
        print(f"{B}■ {e.get('status')} · cost {s.get('session_costs')} · {s.get('tool_calls')} tool calls · "
              f"{round((s.get('duration_ms') or 0) / 1000)}s · task {s.get('task_id')}{X}")
    return ""

if __name__ == "__main__":
    main()
