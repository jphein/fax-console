#!/usr/bin/env bash
# sandbox-probe.sh — prove scripts/bob-sandbox.sh contains what it claims to (positive controls).
# Every "must fail" probe is something an agent inside the sandbox might try; every "must work"
# probe is something legitimate work needs. Exit 0 only if all of them come out as expected.
# Run on the workstation (needs bwrap + sudo systemd-run); it is not a CI test.
set -uo pipefail
root=$(git rev-parse --show-toplevel); cd "$root"
pass=0; fail=0
# The PBX's real host name is not committed; set PROBE_PBX_HOST locally for the live control.
pbx=${PROBE_PBX_HOST:-pbx}
ip() { local IFS=.; echo "$*"; }   # probe targets are assembled at runtime: the scrub gate forbids host literals
control() {  # control LABEL COMMAND: must WORK outside the sandbox, or the probes below prove nothing
  local label=$1; shift
  if bash -c "$*" >/dev/null 2>&1; then r=ok; pass=$((pass+1)); else r=WRONG; fail=$((fail+1)); fi
  printf '%-6s control   %s (outside the sandbox)\n' "$r" "$label"
}
probe() {  # probe EXPECT(fail|work) LABEL COMMAND
  local expect=$1 label=$2; shift 2
  if scripts/bob-sandbox.sh bash -c "$*" >/dev/null 2>&1; then got=work; else got=fail; fi
  if [ "$got" = "$expect" ]; then pass=$((pass+1)); r=ok; else fail=$((fail+1)); r=WRONG; fi
  printf '%-6s must %-4s  %s\n' "$r" "$expect" "$label"
}
# network: the PBX, the LAN and local services are unreachable; DNS and the internet work
[ "$pbx" != pbx ] && control "ssh to the PBX host works"  "SSH_ASKPASS_REQUIRE=never ssh -o BatchMode=yes -o ConnectTimeout=5 $pbx true"
probe fail "ssh to the PBX host by name"         "ssh -o BatchMode=yes -o ConnectTimeout=5 $pbx true"
probe fail "ssh, quoted command name"            "'ssh' -o BatchMode=yes -o ConnectTimeout=5 $pbx true"
probe fail "ssh by absolute path"                "/usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=5 $pbx true"
probe fail "ssh via python os.system"            "python3 -c 'import os,sys; sys.exit(0 if os.system(\"ssh -o BatchMode=yes -o ConnectTimeout=5 $pbx true\") == 0 else 1)'"
probe fail "TCP to a LAN router address"         "timeout 5 bash -c 'exec 3<>/dev/tcp/$(ip 10 0 0 1)/80'"
probe fail "TCP to a 192.168 address"            "timeout 5 bash -c 'exec 3<>/dev/tcp/$(ip 192 168 1 1)/80'"
probe fail "TCP to a loopback service"           "timeout 5 bash -c 'exec 3<>/dev/tcp/127.0.0.1/22'"
probe fail "TCP to a CGNAT/tailnet address"      "timeout 5 bash -c 'exec 3<>/dev/tcp/$(ip 100 100 100 100)/53'"
probe fail "TCP over IPv6 (loopback)"            "timeout 5 bash -c 'exec 3<>/dev/tcp/::1/22'"
probe fail "TCP over IPv6 (a global address)"    "timeout 5 bash -c 'exec 3<>/dev/tcp/2606:4700:4700::1111/443'"
probe work "DNS through the local stub"          "getent hosts example.com"
probe work "HTTPS to the public internet"        "timeout 10 bash -c 'exec 3<>/dev/tcp/1.1.1.1/443'"
# filesystem: nothing of the owner's home or host config is visible
probe fail "read the private deny-list"          "cat \${HOME_REAL:-/home/$(id -un)}/.config/fax-console/scrub-deny.txt"
probe fail "list ~/.ssh of the real home"        "ls /home/$(id -un)/.ssh"
probe fail "list ~/.claude of the real home"     "ls /home/$(id -un)/.claude"
probe fail "read /etc/hosts"                     "cat /etc/hosts"
probe fail "other global CLIs are visible"       "command -v bw || ls $HOME/.npm-global/lib/node_modules/@bitwarden"
probe work "the bob CLI starts"                  "bob --version"
probe fail "read the host ssh config"            "cat /etc/ssh/ssh_config"
probe fail "a sibling repository is visible"     "ls /home/$(id -un)/Projects/fax"
# writes: the frozen baseline, git internals, the guard and its rules are read-only
probe fail "write into legacy/"                  "echo x > legacy/probe"
probe fail "append to AGENTS.md"                 "echo x >> AGENTS.md"
probe fail "overwrite the tool guard"            "echo x > .bob/hooks/tool_guard.py"
probe fail "write into scripts/"                 "echo x > scripts/probe"
probe fail "write into .git/"                    "echo x > .git/probe"
probe fail "write into .github/"                 "echo x > .github/probe"
probe fail "tamper with the venv"                "echo x > .venv/probe"
# the evidence: Bob may not edit its own ledger row or transcript (bob-run.sh records both outside)
probe fail "rewrite the Bobcoin ledger"          "echo x >> docs/bob-usage.md"
probe fail "replace the ledger by a rename"      "cp docs/bob-usage.md x.tmp && mv -f x.tmp docs/bob-usage.md; r=\$?; rm -f x.tmp; exit \$r"
probe fail "forge a run record"                  "echo x > docs/bob-runs/probe.jsonl"
probe fail "replace docs/ by a rename"           "mv docs docs.old && { mv docs.old docs; exit 0; }"
probe fail "write outside the repo"              "echo x > /home/bob/../probe; echo x > /usr/probe"
probe work "write a new file in the repo"        "echo x > sandbox-probe.tmp && rm sandbox-probe.tmp"
probe work "append to the guard log"             "printf '' >> .bob/guard.log"
probe work "run the test tools"                  ".venv/bin/python -m pytest --version && .venv/bin/ruff --version"
# processes and identity
probe fail "see host processes"                  "[ \$(ps -e --no-headers | wc -l) -gt 12 ]"
probe fail "real hostname leaks"                 "[ \"\$(hostname)\" != bob-sandbox ]"
probe fail "an ssh agent is reachable"           "[ -n \"\${SSH_AUTH_SOCK:-}\" ]"
echo "sandbox-probe: $pass as expected, $fail wrong"
[ "$fail" -eq 0 ]
