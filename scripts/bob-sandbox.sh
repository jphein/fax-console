#!/usr/bin/env bash
# bob-sandbox.sh CMD [ARGS...] — run CMD (Bob, or anything Bob wrote) inside an OS sandbox.
#
# This is the security boundary for IBM Bob in this repository. The workspace hooks in .bob/
# are an audit and early-warning layer only: a regex over a shell command line cannot be a
# control (independent review, 2026-09-28), and once Bob may run pytest it runs code it wrote.
# So the whole process tree is confined here instead:
#
#   filesystem (bubblewrap): the repo read-write, except legacy/ .git/ .bob/ scripts/ .github/
#     .venv/ AGENTS.md BASELINE.md LICENSE (read-only); /usr read-only; a minimal /etc (CA
#     certificates, resolver, locale; no /etc/hosts, no ssh config); a synthetic passwd; a clean
#     HOME that holds only Bob's own settings. The owner's real home is not visible at all: no
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
bob_home=${BOB_HOME:-$HOME/.local/share/fax-console/bob-home}
[ "$#" -ge 1 ] || { echo "usage: bob-sandbox.sh CMD [ARGS...]" >&2; exit 2; }

mkdir -p "$bob_home/.bob/settings" "$root/.bob/tmp"
touch "$root/.bob/guard.log"
[ -f "$bob_home/.bob/settings/settings.json" ] ||
  printf '{"licenseConsent": true, "bobShell": {"autoUpdate": false}}\n' > "$bob_home/.bob/settings/settings.json"
printf '{"version": 1, "folders": {"%s": "TRUST_FOLDER"}}\n' "$root" > "$bob_home/.bob/trustedFolders.json"
for d in skills plugins rules; do
  [ -z "$(ls -A "$bob_home/.bob/$d" 2>/dev/null)" ] || { echo "refusing: $bob_home/.bob/$d is not empty" >&2; exit 2; }
done

# Secrets reach the sandbox through a mode-600 file, never argv (argv is visible in ps).
# (Temp files, not fds: sudo closes every inherited descriptor above 2.)
rt=$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/bob-sandbox.XXXXXX"); chmod 700 "$rt"
trap 'rm -rf "$rt"' EXIT
envf="$rt/env"; install -m 600 /dev/null "$envf"
printf '%s:x:%s:%s::/home/bob:/bin/bash\n' "$(id -un)" "$(id -u)" "$(id -g)" > "$rt/passwd"
printf '%s:x:%s:\n' "$(id -gn)" "$(id -g)" > "$rt/group"
{
  printf 'export HOME=/home/bob LANG=C.UTF-8 TERM=%q FAX_CONSOLE_SANDBOX=1\n' "${TERM:-xterm-256color}"
  printf 'export PATH=%q\n' "$root/.venv/bin:$HOME/.npm-global/bin:/usr/bin:/bin"
  printf 'export FAX_CONSOLE_GUARD_LOG=%q\n' "$root/.bob/guard.log"
  [ -n "${BOB_API_KEY:-}" ] && printf 'export BOB_API_KEY=%q\n' "$BOB_API_KEY"
} > "$envf"

ro=()
for p in legacy .git .bob scripts .github .venv AGENTS.md BASELINE.md LICENSE; do
  [ -e "$root/$p" ] && ro+=(--ro-bind "$root/$p" "$root/$p")
done
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
    "${etc[@]}" --ro-bind "$resolv" /etc/resolv.conf \
    --ro-bind "$rt/passwd" /etc/passwd --ro-bind "$rt/group" /etc/group \
    --bind "$bob_home" /home/bob \
    --ro-bind "$HOME/.npm-global" "$HOME/.npm-global" \
    --bind "$root" "$root" "${ro[@]}" \
    --bind "$root/.bob/guard.log" "$root/.bob/guard.log" --bind "$root/.bob/tmp" "$root/.bob/tmp" \
    --ro-bind "$envf" /run/bob-env --chdir "$root" \
    /bin/bash -c 'set -a; . /run/bob-env; set +a; exec "$@"' bob-sandbox "$@"
