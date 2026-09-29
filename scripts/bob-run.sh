#!/usr/bin/env bash
# bob-run.sh N SLUG [MAX_COST] — run one recorded Bob task.
#   Prompt:  docs/bob-runs/N-SLUG.prompt.md (written first, scrub-checked, committed as evidence)
#   Output:  docs/bob-runs/N-SLUG.jsonl       (Bob's stream-json, verbatim)
#            docs/bob-runs/N-SLUG.guard.jsonl (every allow/deny the sandbox hooks decided)
# Bob runs inside scripts/bob-sandbox.sh (the OS sandbox); the .bob/ hooks audit inside it. Rules: AGENTS.md.
set -euo pipefail
n=${1:?run number}; slug=${2:?slug}; cost=${3:-3}
root=$(git rev-parse --show-toplevel); cd "$root"
p="docs/bob-runs/$n-$slug.prompt.md"; out="docs/bob-runs/$n-$slug.jsonl"
[ -f "$p" ] || { echo "no prompt file $p" >&2; exit 2; }
[ -e "$out" ] && { echo "$out exists; runs are append-only" >&2; exit 2; }
scripts/scrub-check.sh --paths "$p" --require-deny
# shellcheck disable=SC1090
source "${BOB_ENV:-$HOME/.config/bob-shell/env}"
# Bob runs inside the OS sandbox (scripts/bob-sandbox.sh): the security boundary. The .bob/ hooks
# inside it are an audit and early-warning layer.
: > .bob/guard.log
scripts/bob-sandbox.sh bob run --format stream-json --max-cost "$cost" --accept-license \
    --disable-tool-groups skill,mcp,browser,mode "$(cat "$p")" | tee "$out" | python3 scripts/bob-watch.py
cp .bob/guard.log "docs/bob-runs/$n-$slug.guard.jsonl"
# The recording is published: relativize the repo path, and make sure no API key can survive in it.
python3 - "$root" "$out" "docs/bob-runs/$n-$slug.guard.jsonl" <<'PY'
import os, sys
root, files = sys.argv[1], sys.argv[2:]
key = os.environ.get("BOB_API_KEY", "")
for f in files:
    t = open(f, encoding="utf-8").read().replace(root + "/", "./").replace(root, ".")
    if len(key) >= 8:
        t = t.replace(key, "***")
    open(f, "w", encoding="utf-8").write(t)
PY
python3 scripts/redact-refused.py "$out"   # a write the guard refused is never published
scripts/scrub-check.sh --paths "$out" "docs/bob-runs/$n-$slug.guard.jsonl" --require-deny
python3 - "$out" <<'PY'
import json, sys
r = [json.loads(l) for l in open(sys.argv[1]) if '"type":"result"' in l.replace(" ", "")]
s = (r[-1].get("stats") if r else {}) or {}
print(f"run cost: {s.get('session_costs')}  tool calls: {s.get('tool_calls')}  task: {s.get('task_id')}")
PY
