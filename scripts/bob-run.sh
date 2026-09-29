#!/usr/bin/env bash
# bob-run.sh N SLUG [MAX_COST] — run one recorded Bob task.
#   Prompt:  docs/bob-runs/N-SLUG.prompt.md (written first, scrub-checked, committed as evidence)
#   Output:  docs/bob-runs/N-SLUG.jsonl       (Bob's stream-json, verbatim)
#            docs/bob-runs/N-SLUG.guard.jsonl (every allow/deny the sandbox hooks decided)
#   Ledger:  docs/bob-usage.md is updated automatically by scripts/bob_usage.py. The run is
#            reserved at MAX_COST before it starts and replaced with Bob's measured cost when it
#            ends, even when Bob fails. Inside the sandbox the ledger and docs/bob-runs/ are
#            read-only, and docs/ cannot be renamed. Bob's stream is recorded outside the repository
#            while it runs, and copied into docs/bob-runs/ only after the sandbox exits, and only if
#            docs/ is still the same directory (exit 3 otherwise; nothing is touched).
# Bob runs inside scripts/bob-sandbox.sh (the OS sandbox); the .bob/ hooks audit inside it. Rules: AGENTS.md.
# Gateway lock, checked on every run (#7): the sandbox saves Bob's own log to a directory named here,
#   and scripts/bob_lock_check.py must find the policy loaded and every request on the pinned origin.
#   Otherwise the run fails (exit 4) and keeps counting at its reservation. It is a regression check:
#   Bob writes that log itself, and the read-only policy file is the lock.
# Every Python here runs with -I (isolated): Bob can write the repo root, and without -I a json.py it
# left there would be imported by these host-side steps, with the API key in the environment.
#
# Budget (see "Budget" in docs/bob-usage.md; the rules are in scripts/bob_usage.py):
#   * refuses (exit 75) when this billing cycle's total + MAX_COST would pass the soft cap
#     (BOB_SOFT_CAP, default 100), unless BOB_OVERRIDE="team-lead: <reason>" is set;
#   * never passes the 180-Bobcoin allotment, a constant that no variable changes;
#   * refuses (exit 2) a run number, slug or MAX_COST that is not well formed, before anything runs;
#   * exits 3 when the run's ledger row went missing (it is restored) or Bob reported an
#     invalid cost (the reservation keeps counting); a run that exits non-zero keeps counting at
#     its reservation too, since a killed run's last result line may not be Bob's;
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
# .bob and its guard log must be real. This script empties the guard log on the host before the run and
# copies it after, and both follow a symlink, so a planted .bob/guard.log -> <host file> would empty that
# file before bob-sandbox.sh ever refused it (the Oracle ab7e64d, PR #14). Checked before anything runs.
for q in .bob .bob/guard.log; do
  [ ! -L "$q" ] || { echo "bob-run: refusing: $q is a symlink" >&2; exit 2; }
done

if [ "${BOB_TMUX:-0}" = 1 ] && [ -z "${BOB_TMUX_INNER:-}" ]; then
  # tmux windows inherit the tmux server's environment, not ours, so pass what matters.
  sess=${BOB_TMUX_SESSION:-bob}; rcf="docs/bob-runs/.run-$n.rc"; rm -f "$rcf" "$rcf.tmp"
  pass=(BOB_TMUX_INNER=1); drop=()
  for v in BOB_OVERRIDE BOB_ENV BOB_SOFT_CAP XDG_STATE_HOME FAX_CONSOLE_SCRUB_DENY; do
    if [ -n "${!v:-}" ]; then pass+=("$v=${!v}"); else drop+=(-u "$v"); fi   # unset here: unset there
  done
  # The window keeps itself open when the run ends (set from inside, so no exit can race it),
  # and writes its exit code to a temp name first, so the caller never reads a half-written rc.
  cmd='tmux set-option -p -t "$TMUX_PANE" remain-on-exit on; '
  cmd+="cd $(printf %q "$root") && env $(printf '%q ' "${drop[@]}" "${pass[@]}")scripts/bob-run.sh"
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
python3 -I scripts/bob_usage.py status "$ledger"
python3 -I scripts/bob_usage.py reserve "$ledger" --n "$n" --slug "$slug" --max-cost "$cost" \
    ${BOB_OVERRIDE:+--override "$BOB_OVERRIDE"}
# shellcheck disable=SC1090
source "${BOB_ENV:-$HOME/.config/bob-shell/env}"
# Bob runs inside the OS sandbox (scripts/bob-sandbox.sh): the security boundary. The .bob/ hooks
# inside it are an audit and early-warning layer.
# Its stream goes to a private file outside the repository, which the sandbox cannot see; the ledger
# is finalized from that file, and the published copy is made after the sandbox has exited.
priv=${XDG_STATE_HOME:-$HOME/.local/state}/fax-console/runs
mkdir -p "$priv"; chmod 700 "$priv"
rec="$priv/$(date +%Y%m%dT%H%M%S)-$$-$n-$slug.jsonl"; install -m 600 /dev/null "$rec"
logdir="${XDG_STATE_HOME:-$HOME/.local/state}/fax-console/bob-logs/$(date +%Y%m%dT%H%M%S)-$$-$n-$slug"
sig() { stat -c '%d:%i' docs docs/bob-runs "$ledger" 2>/dev/null | tr '\n' ' '; }
before=$(sig)
: > .bob/guard.log
set +e      # a failed run must still leave its guard log and its ledger row
FAX_CONSOLE_BOB_LOG_DIR="$logdir" scripts/bob-sandbox.sh bob run --format stream-json --max-cost "$cost" --accept-license \
    --disable-tool-groups skill,mcp,browser,mode "$(cat "$p")" | tee "$rec" | python3 -I scripts/bob-watch.py
rc=${PIPESTATUS[0]}
set -e
if [ "$(sig)" != "$before" ]; then
  echo "bob-run: run $n NOT recorded: docs/ was replaced while Bob ran ($before -> $(sig))." >&2
  echo "bob-run: nothing was copied or finalized; the reservation keeps counting in the journal." >&2
  echo "bob-run: Bob's stream is kept at $rec. Restore docs/ by hand before anything else." >&2
  exit 3
fi
# The gateway lock, from Bob's own log for this run (counts and origins only; see the header).
lock=0
python3 -I scripts/bob_lock_check.py "$logdir" || lock=$?
if [ "$lock" -ne 0 ]; then
  echo "bob-run: run $n FAILED the gateway-lock check on Bob's own log ($logdir); its reservation keeps counting" >&2
  [ "$rc" -ne 0 ] || rc=4
fi
cp "$rec" "$out"
cp .bob/guard.log "docs/bob-runs/$n-$slug.guard.jsonl"
# The recording is published: relativize the repo path, then any other path in the account's
# home (a refused write outside the repo names it), and make sure no API key can survive in it.
python3 -I - "$root" "$out" "docs/bob-runs/$n-$slug.guard.jsonl" <<'PY'
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
# A write the sandbox guard refused is never published: its content is what the guard keeps out. It runs
# on the published copy, before the scrub below; finalize reads the private copy, so costs are unaffected.
python3 -I scripts/redact-refused.py "$out"
fin=0
python3 -I scripts/bob_usage.py finalize "$ledger" --n "$n" --file "$rec" --rc "$rc" --max-cost "$cost" \
    >/dev/null || fin=$?
rm -f "$rec"    # the published, redacted copy in docs/bob-runs/ is the record from here on
scripts/scrub-check.sh --paths "$out" "docs/bob-runs/$n-$slug.guard.jsonl" --require-deny
python3 -I - "$out" <<'PY'
import json, sys
r, bad = [], 0
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    if '"type":"result"' in line.replace(" ", ""):
        try:
            r.append(json.loads(line))
        except ValueError:
            bad += 1                     # a line written into the stream: finalize has already refused its cost
s = (r[-1].get("stats") if r and isinstance(r[-1], dict) else {}) or {}
print(f"run cost: {s.get('session_costs')}  tool calls: {s.get('tool_calls')}  task: {s.get('task_id')}"
      + (f"  ({bad} malformed result line(s))" if bad else ""))
PY
python3 -I scripts/bob_usage.py status "$ledger"
if [ "$fin" -ne 0 ]; then
  echo "bob-run: the ledger needed attention for run $n (finalize exit $fin; see its message above)" >&2
  [ "$rc" -ne 0 ] || rc=$fin
fi
exit "$rc"
