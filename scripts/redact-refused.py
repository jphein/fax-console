#!/usr/bin/env python3
"""redact-refused.py RUN.jsonl — keep writes the sandbox guard refused out of a published recording.

A write the guard refuses (identifying data, a protected path, a path outside the repository)
never reaches the repository. The recording must not publish it either: its content is exactly
what the guard exists to keep out. So each refused call keeps its tool name, its path and the
guard's reason, which is already masked, and its content fields are replaced by a placeholder.
Everything else in the recording stays verbatim.
"""
import json
import sys

CONTENT_KEYS = ("content", "contents", "diff", "patch", "new_str", "new_string", "text",
                "replace", "replacement", "new_content", "code", "edits", "operations", "lines")
PLACEHOLDER = "<not published: the sandbox guard refused this write>"


def refused(result):
    msg = json.dumps((result or {}).get("error") or "")
    return result is not None and result.get("status") != "success" and (
        "write refused" in msg or "path refused" in msg)


def main(path):
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    def parse(line):
        """An event, or None for a line that is not a JSON object: such a line is kept verbatim."""
        try:
            e = json.loads(line) if line.strip() else None
        except ValueError:
            return None
        return e if isinstance(e, dict) else None

    events = [parse(line) for line in lines]
    results = {e["tool_id"]: e for e in events
               if e and e.get("type") == "tool_result" and e.get("tool_id") is not None}
    n, changed = 0, set()
    for i, e in enumerate(events):
        if e and e.get("type") == "tool_use" and refused(results.get(e.get("tool_id"))):
            params = e.get("parameters") or {}
            for k in CONTENT_KEYS:
                if k in params:
                    params[k] = PLACEHOLDER
                    n += 1
                    changed.add(i)
    with open(path, "w", encoding="utf-8") as f:   # untouched lines are written back byte for byte
        for i, (line, e) in enumerate(zip(lines, events, strict=True)):
            out = json.dumps(e, ensure_ascii=False, separators=(",", ":")) if i in changed else line
            f.write(out + "\n")
    print(f"redact-refused: {n} refused write field(s) replaced in {path}", file=sys.stderr)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        main(p)
