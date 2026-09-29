"""scripts/bob_lock_check.py: the per-run gateway-lock check on Bob's own log (drift-gems, #7).

The fixture logs use the six line shapes Aurora extracted from her control runs (2026-09-29), with
fictional timestamps and sizes. An off-origin host is always a reserved example domain.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bob_lock_check.py"
PINNED = "https://api.us-east.bob.ibm.com"


def line(module: str, msg: str, **data) -> str:
    o = {"ts": "2000-01-01T00:00:00.000Z", "level": "debug" if module == "Gateway" else "info",
         "module": module, "msg": msg}
    if data:
        o["data"] = data
    return json.dumps(o)


POLICY = [line("PolicyService", 'Initialising policy watcher on platform "linux"'),
          line("PolicyService", "Reading policy file: /etc/bob/policy.json"),
          line("PolicyService", "Loaded 1 policy/policies from file: GatewayUrl")]


def req(url: str, path: str = "/inference/v1/chat/completions") -> list[str]:
    return [line("Gateway", "HTTP request", method="POST", url=url + path, bodySize=1234),
            line("Gateway", "Response received", status=200, path=path),
            line("Gateway", "HTTP request complete", method="POST", url=url + path, status=200, elapsedMs=42)]


def logdir(tmp_path: Path, *lines: str) -> Path:
    d = tmp_path / "logs"
    (d / "shell").mkdir(parents=True)
    (d / "shell" / "bob-shell-20000101T000000.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return d


def check(d: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(SCRIPT), str(d), *args], capture_output=True,
                          text=True, check=False, timeout=60)


def test_the_policy_and_pinned_requests_pass(tmp_path):
    d = logdir(tmp_path, *POLICY, *req(PINNED, "/admin/v1/profile"), *req(PINNED))
    r = check(d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "bob-lock: OK" in r.stdout and "2 request(s)" in r.stdout and f"{PINNED} x4" in r.stdout
    assert "/inference" not in r.stdout and "/admin" not in r.stdout          # origins only, never a path


@pytest.mark.parametrize("name,lines,why", [
    ("no-policy", req(PINNED), "no policy-loaded line"),                         # Aurora's policy-off run
    ("off-origin", POLICY + req(PINNED) + req("https://attacker.example"), "2 off-origin"),
    ("userinfo", POLICY + req(PINNED + "@attacker.example"), "2 off-origin"),    # any user-info: "?"
    ("backslash-at",                                                             # WHATWG: "\\" is "/"
     POLICY + req("https://elsewhere.example\\@api.us-east.bob.ibm.com"), "2 off-origin"),
    ("tab-in-host", POLICY + req(PINNED + "\t"), "2 off-origin"),                  # fail closed
    ("plain-http", POLICY + req("http://api.us-east.bob.ibm.com"), "2 off-origin"),
    ("other-port", POLICY + req(PINNED + ":8443"), "2 off-origin"),
    ("no-url", POLICY + req(PINNED) + [line("Gateway", "HTTP request", method="GET")], "1 off-origin"),
    ("no-requests", POLICY, "no requests"),
    ("two-policies",                                                             # we write exactly one key
     [line("PolicyService", "Loaded 2 policy/policies from file: GatewayUrl, X")] + req(PINNED),
     "no policy-loaded line"),
])
def test_a_missing_or_broken_lock_fails(tmp_path, name, lines, why):
    r = check(logdir(tmp_path, *lines))
    assert r.returncode == 3 and "FAILED" in r.stdout and why in r.stdout, r.stdout
    assert "/inference" not in r.stdout


def test_an_other_origin_is_printed_as_a_hash_never_as_its_host(tmp_path):
    """A hostname can carry data (the Oracle, #7): only the pinned origin is printed verbatim."""
    other = "https://leaky-label-0123.attacker.example"
    r = check(logdir(tmp_path, *POLICY, *req(PINNED), *req(other)))
    assert r.returncode == 3 and "<other origin " in r.stdout, r.stdout
    assert f", {len(other)} chars> x2" in r.stdout
    assert "attacker" not in r.stdout and "leaky" not in r.stdout and f"{PINNED} x2" in r.stdout


def test_an_ipv6_origin_keeps_its_brackets(tmp_path):
    v6 = "https://[2001:db8::1]:8443"
    d = logdir(tmp_path, *POLICY, *req(v6))
    r = check(d, "--origin", v6)
    assert r.returncode == 0 and f"{v6} x2" in r.stdout, r.stdout


def test_no_log_at_all_is_no_evidence(tmp_path):
    r = check(tmp_path / "never-saved")
    assert r.returncode == 3 and "no Bob log" in r.stdout


def test_key_order_non_json_and_explicit_default_port(tmp_path):
    shuffled = json.dumps({"data": {"url": PINNED + ":443/inference/v1/model/info", "method": "GET"},
                           "msg": "HTTP request", "module": "Gateway", "level": "debug"})
    d = logdir(tmp_path, *POLICY, shuffled, "not json at all", "[1, 2]", '"a string"',
               *req(PINNED.replace("api.", "API.")))
    r = check(d)
    assert r.returncode == 0, r.stdout
    assert "3 line(s) not a JSON object" in r.stdout and f"{PINNED} x3" in r.stdout


def test_another_origin_can_be_pinned(tmp_path):
    d = logdir(tmp_path, *POLICY, *req("https://gateway.example"))
    assert check(d).returncode == 3
    assert check(d, "--origin", "https://gateway.example").returncode == 0


def test_the_pinned_origin_is_the_sandboxs_gateway():
    """One gateway, two files: the check's default must be the origin bob-sandbox.sh pins."""
    sandbox = (ROOT / "scripts" / "bob-sandbox.sh").read_text(encoding="utf-8")
    m = re.search(r"^BOB_GATEWAY=(\S+)$", sandbox, re.MULTILINE)
    assert m and m.group(1) == PINNED
    assert f'PINNED = "{PINNED}"' in SCRIPT.read_text(encoding="utf-8")
