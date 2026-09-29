#!/usr/bin/env python3
"""Render Bob Shell's stream-json on a terminal so a person can watch Bob work.

  bob run --format stream-json ... | tee run.jsonl | scripts/bob-watch.py
"""
import json
import shutil
import sys
import textwrap

W = max(40, min(100, shutil.get_terminal_size((80, 20)).columns - 2))
G, Y, R, D, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def short(v, n=W - 12):
    s = v if isinstance(v, str) else json.dumps(v)
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def main():
    buf = ""
    for line in sys.stdin:
        try:
            e = json.loads(line)
        except ValueError:
            print(D + line.rstrip() + X)
            continue
        t = e.get("type")
        if t == "message" and e.get("role") == "assistant":
            buf += e.get("content", "")
            while "\n" in buf:
                head, buf = buf.split("\n", 1)
                print(G + textwrap.fill(head, W) + X if head.strip() else "")
            continue
        if buf.strip():
            print(G + textwrap.fill(buf, W) + X)
        buf = ""
        if t == "tool_use":
            p = e.get("parameters") or {}
            arg = p.get("command") or p.get("path") or p.get("pattern") or p
            print(f"{Y}▶ {e.get('tool_name')}{X} {short(arg)}")
        elif t == "tool_result":
            if e.get("status") == "success":
                print(f"{D}  ✓ {short(e.get('output', ''))}{X}")
            else:
                print(f"{R}  ✗ {short((e.get('error') or {}).get('message', e.get('error')))}{X}")
        elif t == "result":
            s = e.get("stats") or {}
            print(f"{B}■ {e.get('status')} · cost {s.get('session_costs')} · "
                  f"{s.get('tool_calls')} tool calls · "
                  f"{round((s.get('duration_ms') or 0) / 1000)}s · task {s.get('task_id')}{X}")
    if buf.strip():
        print(G + textwrap.fill(buf, W) + X)


if __name__ == "__main__":
    main()
