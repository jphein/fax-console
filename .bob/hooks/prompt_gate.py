#!/usr/bin/env python3
"""Bob UserPromptSubmit hook: no prompt reaches Bob if it carries identifying data.

The hackathon rules forbid giving personal, confidential or restricted information
to AI tools (§8.6). Reviewing prompts by eye is not enough, so this hook runs
every prompt through scripts/scrub-check.sh (generic rules plus the local private
deny-list) before Bob sees it, and blocks it on any finding.

It FAILS CLOSED: Bob treats a crashed hook as "allow", so every unexpected error
here is turned into a block (exit 2) instead.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = os.environ.get("FAX_CONSOLE_GUARD_LOG") or os.path.join(ROOT, ".bob", "guard.log")


def log(verdict, detail):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"hook": "prompt_gate", "verdict": verdict, "detail": detail}) + "\n")
    except OSError:
        pass


def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))
    print(reason, file=sys.stderr)
    log("block", reason)
    sys.exit(2)


def main():
    try:
        event = json.load(sys.stdin)
        prompt = event.get("prompt") or ""
        r = subprocess.run([os.path.join(ROOT, "scripts", "scrub-check.sh"), "--stdin", "prompt", "--require-deny"],
                           input=prompt.encode("utf-8"), capture_output=True, timeout=15, check=False)
    except Exception as e:  # noqa: BLE001 -- fail closed: Bob treats a crashed hook as "allow"
        block(f"prompt gate could not run ({type(e).__name__}); refusing the prompt")
    if r.returncode == 0:
        log("allow", f"{len(prompt)} chars")
        sys.exit(0)
    findings = r.stdout.decode("utf-8", "replace").strip() or r.stderr.decode("utf-8", "replace").strip()
    block("prompt refused: it contains identifying data (masked): " + findings.replace("\n", "; ")[:600])


if __name__ == "__main__":
    main()
