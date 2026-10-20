#!/usr/bin/env python3
"""redact-refused.py RUN.jsonl — keep calls the sandbox guard refused out of a published recording.

A call the guard refuses (identifying data, a protected path, a path outside the repository)
never reaches the repository, and the recording must not publish it either. Redaction is by
ALLOWLIST (Oracle review of PR #47): a refused call keeps its tool name and its top-level path
parameters (keys matched case-insensitively against the guard's PATH_KEYS, plain string values
only); every other parameter, at any depth and in any case (content, Content, body, command,
files[...]), becomes a placeholder. On a path refusal the path itself is masked too, since a path
outside the repository can be identifying. The guard's reason is already masked.

Not covered here: assistant messages and thinking that restate refused content. The published
stream is still scrubbed as a whole afterwards (bob-run.sh runs scrub-check on it, and CI's scrub
gate runs on every push), which catches identifying data wherever it appears.
"""
import json
import sys

# Same set as .bob/hooks/tool_guard.py PATH_KEYS (tests/test_redact_refused.py checks they match).
PATH_KEYS = ("path", "file_path", "filepath", "target_file", "file", "paths", "files", "target",
             "destination", "source", "directory", "dir", "cwd")
PLACEHOLDER = "<not published: the sandbox guard refused this write>"
PATH_PLACEHOLDER = "<path not published: the sandbox guard refused it>"
PATH_REFUSAL = ("path refused", "outside the repository")


# Every refusal from .bob/hooks/tool_guard.py starts with this marker, whichever rule fired. The two older
# phrases cover recordings made before the marker existed (the review of PR 8: a refusal by the Bob-config
# rule, or by the guard failing closed, had kept its content).
MARKERS = ("sandbox guard:", "write refused", "path refused")


def repo_relative(p):
    """A plain path inside the repository, judged from the value itself (never from the guard's reason):
    relative, no ~, no .. component, no backslashes or NULs. Anything else is masked."""
    if not p or p.startswith(("/", "~")) or "\\" in p or "\0" in p:
        return False
    return ".." not in p.replace("\\", "/").split("/")


def refused(result):
    msg = json.dumps((result or {}).get("error") or "")
    return result is not None and result.get("status") != "success" and any(m in msg for m in MARKERS)


def tool_id(e):
    """The event's tool id, or None when it is missing or not a plain str or int (never a crash)."""
    t = e.get("tool_id")
    return t if isinstance(t, (str, int)) and not isinstance(t, bool) else None


def main(path):
    with open(path, encoding="utf-8") as fh:
        # split("\n"), never splitlines(): that also splits on U+2028, U+2029 and U+0085, which a JSON
        # stream may carry raw inside a string, and it would break one event into two non-JSON lines.
        data = fh.read()
    lines = data.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    def parse(line):
        """An event, or None for a line that is not a JSON object: such a line is kept verbatim."""
        try:
            e = json.loads(line) if line.strip() else None
        except ValueError:
            return None
        return e if isinstance(e, dict) else None

    events = [parse(line) for line in lines]
    results = {tool_id(e): e for e in events
               if e and e.get("type") == "tool_result" and tool_id(e) is not None}
    n, changed = 0, set()
    for i, e in enumerate(events):
        if e and e.get("type") == "tool_use" and tool_id(e) is not None and refused(results.get(tool_id(e))):
            params = e.get("parameters")
            if not isinstance(params, dict):                # a string or list: nothing to keep
                if params not in (None, PLACEHOLDER):
                    e["parameters"] = PLACEHOLDER
                    n += 1
                    changed.add(i)
                continue
            reason = json.dumps((results.get(tool_id(e)) or {}).get("error") or "")
            path_refusal = any(m in reason for m in PATH_REFUSAL)
            # Rebuild from scratch: only allowlisted path keys survive (by name), everything else, key
            # names included, collapses into one marker (cross-model review: names could carry data).
            rebuilt = {}
            for k, v in params.items():
                if isinstance(k, str) and k.lower() in PATH_KEYS and isinstance(v, str):
                    rebuilt[k] = v if (not path_refusal and repo_relative(v)) else PATH_PLACEHOLDER
            if len(rebuilt) < len(params):
                rebuilt["_redacted"] = PLACEHOLDER
            if rebuilt != params:
                e["parameters"] = rebuilt
                n += 1
                changed.add(i)
    if not changed:                                 # nothing refused: the file is left exactly as it was
        print(f"redact-refused: 0 refused write field(s) replaced in {path}", file=sys.stderr)
        return
    with open(path, "w", encoding="utf-8") as f:   # untouched lines are written back byte for byte
        for i, (line, e) in enumerate(zip(lines, events, strict=True)):
            out = json.dumps(e, ensure_ascii=False, separators=(",", ":")) if i in changed else line
            f.write(out + "\n")
    print(f"redact-refused: {n} refused write field(s) replaced in {path}", file=sys.stderr)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        main(p)
