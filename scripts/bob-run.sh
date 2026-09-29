#!/usr/bin/env bash
# bob-run.sh N SLUG [MAX_COST] — run one recorded Bob task.
#   Prompt:  docs/bob-runs/N-SLUG.prompt.md (written first, scrub-checked, committed as evidence)
#   Output:  docs/bob-runs/N-SLUG.jsonl       (Bob's stream-json, verbatim)
#            docs/bob-runs/N-SLUG.guard.jsonl (every allow/deny the sandbox hooks decided)
#   Ledger:  docs/bob-usage.md is updated automatically by scripts/bob_usage.py. The run is
#            reserved at MAX_COST before it starts and replaced with Bob's measured cost when it
#            ends, even when Bob fails. Inside the sandbox the ledger and docs/bob-runs/ are
#            read-only: Bob's stream is recorded out here, by tee.
# Bob runs inside scripts/bob-sandbox.sh (the OS sandbox); the .bob/ hooks audit inside it. Rules: AGENTS.md.
#
# Budget (see "Budget" in docs/bob-usage.md; the rules are in scripts/bob_usage.py):
#   * refuses (exit 75) when this billing cycle's total + MAX_COST would pass the soft cap
#     (BOB_SOFT_CAP, default 100), unless BOB_OVERRIDE="team-lead: <reason>" is set;
#   * never passes the 180-Bobcoin allotment, a constant that no variable changes;
#   * refuses (exit 2) a run number, slug or MAX_COST that is not well formed, before anything runs;
#   * exits 3 when the run's ledger row went missing (it is restored) or Bob reported an
#     invalid cost (the reservation keeps counting);
#   * the cycle total is printed before and after every run.
# BOB_TMUX=1 runs the task in a window of tmux session `bob` (watch it: tmux attach -t bob). A
#   caller that dies, such as an agent's tool timeout, then cannot kill the run or lose its
#   ledger row; the caller just waits. BOB_TMUX_SESSION picks another session.
set -euo pipefail
n=${1:?run number}; slug=${2:?slug}; cost=${3:-3}
[[ $n =~ ^[0-9]{1,6}$ ]] || { echo "bob-run: the run number must be 1-6 digits" >&2; exit 2; }
[[ $slug =~ ^[a-z0-9][a-z0-9-]{0,59}$ ]] || { echo "bob-run: the slug must be lower-case letters, digits and '-'" >&2; exit 2; }
[[ $cost =~ ^[0-9]{1,3}([.][0-9]{1,3})?$ ]] && awk -v c="$cost" 'BEGIN { exit !(c > 0 && c <= 180) }' ||
  { echo "bob-run: MAX_COST must be a number in (0, 180], such as 3 or 2.5" >&2; exit 2; }
root=$(git rev-parse --show-toplevel); cd "$root"
p="docs/bob-runs/$n-$slug.prompt.md"; out="docs/bob-runs/$n-$slug.jsonl"
ledger=docs/bob-usage.md
[ -f "$p" ] || { echo "no prompt file $p" >&2; exit 2; }
[ -e "$out" ] && { echo "$out exists; runs are append-only" >&2; exit 2; }

if [ "${BOB_TMUX:-0}" = 1 ] && [ -z "${BOB_TMUX_INNER:-}" ]; then
  # tmux windows inherit the tmux server's environment, not ours, so pass what matters.
  sess=${BOB_TMUX_SESSION:-bob}; rcf="docs/bob-runs/.run-$n.rc"; rm -f "$rcf" "$rcf.tmp"
  pass=(BOB_TMUX_INNER=1)
  for v in BOB_OVERRIDE BOB_ENV BOB_SOFT_CAP XDG_STATE_HOME FAX_CONSOLE_SCRUB_DENY; do
    if [ -n "${!v:-}" ]; then pass+=("$v=${!v}"); fi
  done
  # The window keeps itself open when the run ends (set from inside, so no exit can race it),
  # and writes its exit code to a temp name first, so the caller never reads a half-written rc.
  cmd='tmux set-option -p -t "$TMUX_PANE" remain-on-exit on; '
  cmd+="cd $(printf %q "$root") && env $(printf '%q ' "${pass[@]}")scripts/bob-run.sh"
  cmd+=" $(printf '%q ' "$n" "$slug" "$cost"); echo \$? > $(printf %q "$rcf.tmp") && mv -f $(printf '%q ' "$rcf.tmp" "$rcf")"
  # "=name" matches the session exactly: a bare name would also match a longer one by prefix.
  tmux has-session -t "=$sess" 2>/dev/null || tmux new-session -d -s "$sess" -n home -c "$root"
  tmux new-window -d -t "=$sess:" -n "run-$n" "$cmd"
  echo "bob-run: run $n is in tmux $sess:run-$n (watch: tmux attach -t $sess)" >&2
  deadline=$(( $(date +%s) + ${BOB_WAIT_TIMEOUT:-7200} ))
  until [ -f "$rcf" ]; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "bob-run: stopped waiting; run $n continues in tmux" >&2; exit 124
    fi
    sleep 2
  done
  rc=$(cat "$rcf"); rm -f "$rcf"
  [[ $rc =~ ^[0-9]+$ ]] || { echo "bob-run: run $n left no exit code; see tmux $sess:run-$n" >&2; exit 1; }
  exit "$rc"
fi

scripts/scrub-check.sh --paths "$p" --require-deny
python3 scripts/bob_usage.py status "$ledger"
python3 scripts/bob_usage.py reserve "$ledger" --n "$n" --slug "$slug" --max-cost "$cost" \
    ${BOB_OVERRIDE:+--override "$BOB_OVERRIDE"}
# shellcheck disable=SC1090
source "${BOB_ENV:-$HOME/.config/bob-shell/env}"
# Bob runs inside the OS sandbox (scripts/bob-sandbox.sh): the security boundary. The .bob/ hooks
# inside it are an audit and early-warning layer.
: > .bob/guard.log
set +e      # a failed run must still leave its guard log and its ledger row
scripts/bob-sandbox.sh bob run --format stream-json --max-cost "$cost" --accept-license \
    --disable-tool-groups skill,mcp,browser,mode "$(cat "$p")" | tee "$out" | python3 scripts/bob-watch.py
rc=${PIPESTATUS[0]}
set -e
cp .bob/guard.log "docs/bob-runs/$n-$slug.guard.jsonl"
# The recording is published: relativize the repo path, then any other path in the account's
# home (a refused write outside the repo names it), and make sure no API key can survive in it.
python3 - "$root" "$out" "docs/bob-runs/$n-$slug.guard.jsonl" <<'PY'
import os, sys
root, files = sys.argv[1], sys.argv[2:]
key = os.environ.get("BOB_API_KEY", "")
home = os.path.expanduser("~").rstrip("/")
for f in files:
    t = open(f, encoding="utf-8").read().replace(root + "/", "./").replace(root, ".")
    if len(home) > 1:
        t = t.replace(home + "/", "~/")
    if len(key) >= 8:
        t = t.replace(key, "***")
    open(f, "w", encoding="utf-8").write(t)
PY
fin=0
python3 scripts/bob_usage.py finalize "$ledger" --n "$n" --file "$out" --rc "$rc" >/dev/null || fin=$?
scripts/scrub-check.sh --paths "$out" "docs/bob-runs/$n-$slug.guard.jsonl" --require-deny
python3 - "$out" <<'PY'
import json, sys
r = [json.loads(l) for l in open(sys.argv[1]) if '"type":"result"' in l.replace(" ", "")]
s = (r[-1].get("stats") if r else {}) or {}
print(f"run cost: {s.get('session_costs')}  tool calls: {s.get('tool_calls')}  task: {s.get('task_id')}")
PY
python3 scripts/bob_usage.py status "$ledger"
if [ "$fin" -ne 0 ]; then
  echo "bob-run: the ledger needed attention for run $n (finalize exit $fin; see its message above)" >&2
  [ "$rc" -ne 0 ] || rc=$fin
fi
exit "$rc"
