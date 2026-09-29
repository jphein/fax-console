#!/usr/bin/env bash
# bob-sandbox.sh CMD [ARGS...] — run CMD (Bob, or anything Bob wrote) inside an OS sandbox.
#
# This is the security boundary for IBM Bob in this repository. The workspace hooks in .bob/
# are an audit and early-warning layer only: a regex over a shell command line cannot be a
# control (independent review, 2026-09-28), and once Bob may run pytest it runs code it wrote.
# So the whole process tree is confined here instead:
#
#   filesystem (bubblewrap): the repo read-write, except legacy/ .git/ .bob/ scripts/ .github/
#     .venv/ AGENTS.md BASELINE.md LICENSE and the evidence, docs/bob-usage.md and docs/bob-runs/
#     (read-only: bob-run.sh records Bob's stream and keeps the ledger from outside), and docs/
#     itself cannot be renamed (it is bound onto itself, a mount point); /usr
#     read-only; a minimal /etc (CA
#     certificates, resolver, locale; no /etc/hosts, no ssh config); a synthetic passwd; a HOME
#     made fresh for every start that holds only Bob's own settings (nothing survives into the next
#     run), and Bob's gateway pinned; of the global npm tree, only the bobshell package. The owner's real home is not visible at all: no
#     ~/.ssh, no ~/.config, no ~/.claude (Bob lists every skill it finds there in its prompt).
#   network (systemd scope, BPF): LAN, loopback, link-local and CGNAT ranges and ALL of IPv6 denied,
#     except the local DNS stub; the public IPv4 internet stays open so Bob can reach its API. The PBX and every
#     house service are unreachable, and ssh has no keys, no agent and no config in any case.
#   processes: own PID, IPC and UTS namespaces (hostname "bob-sandbox"), a new session, and the
#     sandbox dies with its parent.
#
# Everything Bob writes that later executes (tests, conftest.py) must run here or in CI.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
[ "$#" -ge 1 ] || { echo "usage: bob-sandbox.sh CMD [ARGS...]" >&2; exit 2; }
# Bob Shell 2.0.5's own gateway and login (its built-in defaults). The gateway is pinned by Bob's own
# enterprise policy, /etc/bob/policy.json, bound read-only below: the policy locks settings.gatewayUrl
# at every load and reload, and in the bundle's own words "users and CLI flags cannot override this
# value". A settings file alone would win over the flag and the environment on the config-apply path
# (baseUrl = settings.gatewayUrl ?? policy ?? default; Aurora's A/B test, 9/29), and a mid-run write
# to it is reloaded. The environment pin covers the other path (flag ?? BOB_GATEWAY_URL ?? settings).
BOB_GATEWAY=https://api.us-east.bob.ibm.com
BOB_WEB_LOGIN=https://bob.ibm.com
# Bob Shell loads a .env from its working directory, the repo root, and that could set other values.
[ ! -e "$root/.env" ] || { echo "refusing: $root/.env exists, and Bob would load it" >&2; exit 2; }
# It also lists every skill it finds in the workspace (.claude/skills, .agents/skills) in its prompt, and
# the repo is writable: a skill one run leaves there would steer the next (the Oracle, 9/29 01:4x).
for d in .claude .agents; do
  [ -z "$(ls -A "$root/$d" 2>/dev/null)" ] || { echo "refusing: $root/$d is not empty; Bob would read skills there" >&2; exit 2; }
done
[ -z "${BOB_HOME:-}" ] || echo "bob-sandbox: BOB_HOME is ignored: Bob's home is made fresh for every start" >&2
# Bob's own logs are kept, as data, outside the repository: one directory per start. bob-run.sh names
# it (FAX_CONSOLE_BOB_LOG_DIR) so it can check that run's log afterwards (scripts/bob_lock_check.py);
# any other caller gets a timestamped one. The name must be new and under $logs. Checked before
# anything is touched. The variable never reaches Bob, because the sandbox starts from --clearenv.
logs=${XDG_STATE_HOME:-$HOME/.local/state}/fax-console/bob-logs
logdir=${FAX_CONSOLE_BOB_LOG_DIR:-$logs/$(date +%Y%m%dT%H%M%S)-$$}
case "$logdir" in
  "$logs"/*/*|*/../*|*/..|*/./*|*/.) echo "refusing: FAX_CONSOLE_BOB_LOG_DIR must be one plain directory name under $logs" >&2; exit 2 ;;
  "$logs"/?*) ;;
  *) echo "refusing: FAX_CONSOLE_BOB_LOG_DIR must be under $logs" >&2; exit 2 ;;
esac
[ ! -e "$logdir" ] || { echo "refusing: $logdir exists; every start gets a new log directory" >&2; exit 2; }

mkdir -p "$root/.bob/tmp"
touch "$root/.bob/guard.log"

# Secrets reach the sandbox through a mode-600 file, never argv (argv is visible in ps).
# (Temp files, not fds: sudo closes every inherited descriptor above 2.)
rt=$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/bob-sandbox.XXXXXX"); chmod 700 "$rt"
# Bob's home is made fresh from the template for every start, and removed afterwards: one run must not
# leave anything the next run reads (a settings.json naming its own gateway, a .env). Its logs go to
# $logdir (above).
bob_home="$rt/home"
save_logs() {
  if [ -d "$bob_home/.bob/logs" ]; then
    mkdir -p "$logs" && cp -r "$bob_home/.bob/logs" "$logdir" 2>/dev/null
  fi
  return 0
}
trap 'save_logs; rm -rf "$rt"' EXIT
mkdir -p "$bob_home/.bob/settings"
printf '{"licenseConsent": true, "bobShell": {"autoUpdate": false}}\n' > "$bob_home/.bob/settings/settings.json"
printf '{"version": 1, "folders": {"%s": "TRUST_FOLDER"}}\n' "$root" > "$bob_home/.bob/trustedFolders.json"
# Bob lists every skill it can find in its prompt: nothing but its own settings may live in this home.
for d in .bob/skills .bob/plugins .bob/rules .claude .agents; do
  [ -z "$(ls -A "$bob_home/$d" 2>/dev/null)" ] || { echo "refusing: $bob_home/$d is not empty" >&2; exit 2; }
done
envf="$rt/env"; install -m 600 /dev/null "$envf"
printf '%s:x:%s:%s::/home/bob:/bin/bash\n' "$(id -un)" "$(id -u)" "$(id -g)" > "$rt/passwd"
printf '%s:x:%s:\n' "$(id -gn)" "$(id -g)" > "$rt/group"
{
  printf 'export HOME=/home/bob LANG=C.UTF-8 TERM=%q FAX_CONSOLE_SANDBOX=1\n' "${TERM:-xterm-256color}"
  printf 'export PATH=%q\n' "$root/.venv/bin:$HOME/.npm-global/bin:/usr/bin:/bin"
  printf 'export FAX_CONSOLE_GUARD_LOG=%q\n' "$root/.bob/guard.log"
  printf 'export BOB_GATEWAY_URL=%q VITE_GATEWAY_BASE_URL=%q BOB_WEB_LOGIN_URL=%q VITE_WEB_LOGIN_URL=%q\n' \
    "$BOB_GATEWAY" "$BOB_GATEWAY" "$BOB_WEB_LOGIN" "$BOB_WEB_LOGIN"
  [ -n "${BOB_API_KEY:-}" ] && printf 'export BOB_API_KEY=%q\n' "$BOB_API_KEY"
} > "$envf"

ro=()
# Read-only inside the sandbox: the frozen baseline, git, the guard, the tooling and the evidence; and
# every path the HOST later executes or sends (the Oracle via Aurora, PR #8 S2). That covers
# docs/deck (build.sh runs fill.py on the host), docs/video (narration.mjs), demo/ (the test page the
# host faxes to a public inbox) and scratch/ (the orchestrators' scripts). The three tracked ones are
# made first if they are missing, so they are always bound. Otherwise Bob could create docs/deck/fill.py
# in a tree that lacked the directory, and a later host build would run it (the Oracle, PR #9). scratch/
# is bound whenever it exists. The orchestrators keep theirs outside Bob's view, and nothing on the host
# runs a scratch/ it did not write.
for p in docs/deck docs/video demo; do mkdir -p "$root/$p"; done
for p in legacy .git .bob scripts .github .venv AGENTS.md BASELINE.md LICENSE docs/bob-usage.md docs/bob-runs \
         docs/deck docs/video demo scratch; do
  [ -e "$root/$p" ] && ro+=(--ro-bind "$root/$p" "$root/$p")
done
# docs/ bound onto itself is a mount point, which cannot be renamed. Renaming it would carry the
# read-only ledger and run records away and let a new docs/ stand in their place (Oracle, 9/29).
docs_bind=()
[ -d "$root/docs" ] && docs_bind=(--bind "$root/docs" "$root/docs")
printf '{"GatewayUrl": "%s"}\n' "$BOB_GATEWAY" > "$rt/policy.json"; chmod 644 "$rt/policy.json"
# The lock is only a lock if Bob can read it: refuse to start unless it parses to exactly that one key.
python3 -I -c 'import json, sys; p = json.load(open(sys.argv[1])); sys.exit(0 if p == {"GatewayUrl": sys.argv[2]} else 1)' \
  "$rt/policy.json" "$BOB_GATEWAY" || { echo "refusing: the gateway policy does not parse to its one key" >&2; exit 2; }
etc=()
for p in /etc/ssl /etc/ca-certificates /etc/ld.so.cache /etc/ld.so.conf /etc/ld.so.conf.d /etc/nsswitch.conf \
         /etc/localtime /etc/alternatives /etc/gai.conf /etc/host.conf /etc/protocols /etc/services; do
  [ -e "$p" ] && etc+=(--ro-bind "$p" "$p")
done
resolv=$(readlink -f /etc/resolv.conf)

# All of IPv6 is denied: a house LAN may be reachable on-link through global IPv6 addresses that no
# private-range list covers, and Bob needs none (its API is reached over IPv4).
deny="10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16 127.0.0.0/8 ::/0"
sudo -n systemd-run --scope --quiet --collect --uid="$(id -u)" --gid="$(id -g)" \
  -p "IPAddressDeny=$deny" -p "IPAddressAllow=127.0.0.53" -- \
  bwrap --die-with-parent --new-session --unshare-pid --unshare-ipc --unshare-uts --unshare-cgroup-try \
    --hostname bob-sandbox --clearenv \
    --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/sbin /sbin \
    --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
    --proc /proc --dev /dev --tmpfs /tmp --tmpfs /run --tmpfs /home --dir /etc \
    "${etc[@]}" --ro-bind "$resolv" /etc/resolv.conf --dir /etc/bob --ro-bind "$rt/policy.json" /etc/bob/policy.json \
    --ro-bind "$rt/passwd" /etc/passwd --ro-bind "$rt/group" /etc/group \
    --bind "$bob_home" /home/bob \
    --ro-bind "$HOME/.npm-global/lib/node_modules/bobshell" "$HOME/.npm-global/lib/node_modules/bobshell" \
    --dir "$HOME/.npm-global/bin" --symlink ../lib/node_modules/bobshell/dist/bob.js "$HOME/.npm-global/bin/bob" \
    --bind "$root" "$root" "${docs_bind[@]}" "${ro[@]}" \
    --bind "$root/.bob/guard.log" "$root/.bob/guard.log" --bind "$root/.bob/tmp" "$root/.bob/tmp" \
    --ro-bind "$envf" /run/bob-env --chdir "$root" \
    /bin/bash -c 'set -a; . /run/bob-env; set +a; exec "$@"' bob-sandbox "$@"
