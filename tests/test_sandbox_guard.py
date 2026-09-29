"""Regression tests for the Bob sandbox (.bob/hooks) and the scrub gate (scripts/scrub-check.sh).

Written by the orchestrating agent (Claude), not by Bob: these guard the guard. Each rule has a
case that must pass and a case that must be refused, so a rule that silently stops matching
(an instrument that cannot see) fails here instead of in production.
"""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(ROOT, ".bob", "hooks", "tool_guard.py")
GATE = os.path.join(ROOT, ".bob", "hooks", "prompt_gate.py")
SCRUB = os.path.join(ROOT, "scripts", "scrub-check.sh")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    """The hooks demand a deny-list (--require-deny), and a list with no entries is refused. Tests
    use a one-entry list that matches nothing real, so only the generic rules decide and the
    results are the same on any machine, CI included."""
    deny = tmp_path_factory.mktemp("scrub") / "deny.txt"
    deny.write_text("# one entry that matches nothing real: generic rules decide\nzz-no-real-value-zz\n")
    log = tmp_path_factory.mktemp("guard") / "guard.log"      # never the real run log
    return dict(os.environ, FAX_CONSOLE_SCRUB_DENY=str(deny), FAX_CONSOLE_GUARD_LOG=str(log), CI="1")


def hook(script, payload, env):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, "-I", script], input=data.encode(), capture_output=True, env=env,
                          timeout=30, check=False).returncode


def cmd(c):
    return {"tool_name": "execute_command", "tool_input": {"command": c}}


def j(*parts):
    """Test vectors that MUST trip the scrub gate are assembled at runtime, so this file's own
    source passes the gate it tests (no allow-pragma exists: an agent could write through one)."""
    return "".join(parts)


BAD_IP = j("10.", "0.9.9")                    # RFC 1918
BAD_IP2 = j("172.", "20.3.4")
BAD_IP3 = j("10.", "0.0.1")
BAD_PHONE = j("(530) ", "555-", "1234")      # NANP, outside the fictional 555-01xx block
BAD_PHONE2 = j("530 ", "555 ", "1234")
BAD_EMAIL = j("someone", "@", "gmail.com")
BAD_CRED = j("api_pass", "word=", "hunter22")
BAD_IMSI = j("31015", "0123456789")           # 15 digits, IMSI-shaped


ALLOWED = [
    # stdlib shadowing: package modules and ordinary test names stay writable (the review, 9/29)
    {"tool_name": "write_file", "tool_input": {"path": "faxcli/numbers.py", "content": "x = 1"}},
    {"tool_name": "write_file", "tool_input": {"path": "tests/test_json_shapes.py", "content": "x = 1"}},
    {"tool_name": "write_file", "tool_input": {"path": "faxcli/phone_numbers.py", "content": "x = 1"}},
    cmd("cp faxcli/numbers.py faxcli/phone_numbers.py"),
    cmd("python3 -m pytest -q"),
    cmd(".venv/bin/python -m pytest tests/test_x.py -q"),
    cmd(".venv/bin/ruff check faxcli tests"),
    cmd("git diff --stat && git status --short"),
    cmd("git log --oneline -5 && git show HEAD --stat"),
    cmd("grep -n fax_cli legacy/console/telephony-console.py | head"),
    cmd("wc -l legacy/fax/fax/cli.py"),
    cmd("python3 -m py_compile legacy/console/telephony-console.py"),
    cmd("ls " + os.path.join(ROOT, "legacy")),
    cmd("/usr/bin/env python3 -c 'print(1)' > /dev/null"),
    {"tool_name": "write_file", "tool_input": {"path": "docs/analysis.md", "content": "# ok\n202-555-0100"}},
    {"tool_name": "read_file", "tool_input": {"path": "legacy/console/telephony-console.py"}},
    {"tool_name": "update_todo_list", "tool_input": {"todos": "[-] write tests"}},
]

REFUSED = [
    # a stdlib-named module at the root, in tests/ or in scripts/ would run under the host's python3 -c
    {"tool_name": "write_file", "tool_input": {"path": "json.py", "content": "x = 1"}},
    {"tool_name": "write_file", "tool_input": {"path": "./hashlib.py", "content": "x = 1"}},
    {"tool_name": "write_file", "tool_input": {"path": "tests/re.py", "content": "x = 1"}},
    {"tool_name": "write_file", "tool_input": {"path": "subprocess/__init__.py", "content": "x = 1"}},
    {"tool_name": "rename_file", "tool_input": {"path": "notes.py", "target": "json.py"}},
    cmd("cp faxcli/numbers.py json.py"),
    cmd("touch tests/subprocess.py"),
    # Bob's own configuration: a planted gateway would carry the API key elsewhere
    cmd("cd && cat .bob/settings/settings.json"),
    cmd("echo gatewayUrl=local > s.cfg"),              # URL-free: this rule alone must refuse it
    {"tool_name": "write_file", "tool_input": {"path": "docs/x.json", "content": '{"gatewayUrl": "https://gw.example.net"}'}},
    cmd("BOB_GATEWAY_URL=local true"),
    cmd("ssh pbx asterisk -rx 'fax show stats'"),
    cmd("echo x; curl http://example.com"),
    cmd("git push origin main"),
    cmd("git commit -am wip"),
    cmd("git stash"),
    cmd("git restore faxcli/cli.py"),
    cmd("git -c core.pager=less log"),
    cmd("git -C .. status"),
    cmd("pip install requests"),
    cmd("python3 -m pip install ruff"),
    cmd("sudo true"),
    cmd("cat ~/.config/fax-console/scrub-deny.txt"),
    cmd("ls .."),
    cmd("cat /etc/hostname"),
    cmd("ls /"),
    cmd("python3 legacy/fax/fax/cli.py status"),
    cmd("legacy/fax/bin/fax status"),
    cmd("FAX_TZ=UTC python3 legacy/console/telephony-console.py"),
    cmd("cd . && python3 -m faxcli status"),
    cmd(".venv/bin/faxcli status --json"),
    cmd("bob run hello"),
    {"tool_name": "write_file", "tool_input": {"path": "legacy/fax/fax/cli.py", "content": "x"}},
    {"tool_name": "apply_diff", "tool_input": {"path": ".bob/hooks/tool_guard.py", "diff": "-a\n+b"}},
    {"tool_name": "write_file", "tool_input": {"path": "AGENTS.md", "content": "no rules"}},
    {"tool_name": "write_file", "tool_input": {"path": "scripts/scrub-check.sh", "content": "exit 0"}},
    {"tool_name": "write_file", "tool_input": {"path": "docs/a.md", "content": "host " + BAD_IP}},
    {"tool_name": "write_file", "tool_input": {"path": "docs/a.md", "content": "call " + BAD_PHONE}},
    {"tool_name": "write_file", "tool_input": {"path": "/etc/passwd", "content": "x"}},
    {"tool_name": "read_file", "tool_input": {"path": "../outside/README.md"}},
    {"tool_name": "web_fetch", "tool_input": {"url": "https://example.com"}},
    "not json",
]


@pytest.mark.parametrize("payload", ALLOWED, ids=lambda p: json.dumps(p)[:60])
def test_guard_allows(payload, env):
    assert hook(GUARD, payload, env) == 0


@pytest.mark.parametrize("payload", REFUSED, ids=lambda p: json.dumps(p)[:60])
def test_guard_refuses(payload, env):
    assert hook(GUARD, payload, env) == 2


def test_prompt_gate_allows_clean_prompt(env):
    assert hook(GATE, {"prompt": "Analyse legacy/ and write docs/analysis.md; use 202-555-0142."}, env) == 0


def test_prompt_gate_blocks_identifying_prompt(env):
    assert hook(GATE, {"prompt": f"the house line is {BAD_PHONE2}, host {BAD_IP}"}, env) == 2


def test_prompt_gate_fails_closed_on_garbage(env):
    assert hook(GATE, "garbage", env) == 2


@pytest.mark.parametrize("text,expect", [
    ("fictional 202-555-0142 and Faxbeep 1-972-532-9272", 0),
    ("doc range 192.0.2.20 and loopback 127.0.0.1", 0),
    ("a SIP contact 2007@192.0.2.131", 0),
    ("real-looking " + BAD_PHONE, 1),
    (f"private {BAD_IP2} at the end {BAD_IP3}.", 1),
    ("mail " + BAD_EMAIL, 1),
    (BAD_CRED, 1),
    ("an IMSI-shaped " + BAD_IMSI, 1),
])
def test_scrub_check_stdin(text, expect, env):
    r = subprocess.run([SCRUB, "--stdin", "t"], input=text.encode(), capture_output=True, env=env, timeout=30,
                       check=False)
    assert r.returncode == expect, r.stdout.decode()
    assert b"555-1234" not in r.stdout and b"hunter22" not in r.stdout   # matches are masked in output


def test_prompt_gate_inside_sandbox_uses_generic_rules(tmp_path):
    """Inside bob-sandbox.sh the private deny-list is invisible by design: the gate still runs
    the generic rules (and the private list is applied outside, before the prompt is sent)."""
    env = dict(os.environ, FAX_CONSOLE_SANDBOX="1", FAX_CONSOLE_SCRUB_DENY=str(tmp_path / "absent.txt"),
               FAX_CONSOLE_GUARD_LOG=str(tmp_path / "g.log"), CI="1")
    assert hook(GATE, {"prompt": "write tests for faxcli with 202-555-0142"}, env) == 0
    assert hook(GATE, {"prompt": "the line is " + BAD_PHONE}, env) == 2


def test_prompt_gate_outside_sandbox_fails_closed_without_deny_list(tmp_path):
    env = dict(os.environ, FAX_CONSOLE_SCRUB_DENY=str(tmp_path / "absent.txt"),
               FAX_CONSOLE_GUARD_LOG=str(tmp_path / "g.log"), CI="1")
    env.pop("FAX_CONSOLE_SANDBOX", None)
    assert hook(GATE, {"prompt": "a perfectly clean prompt"}, env) == 2


@pytest.mark.parametrize("text,expect", [
    (j("deny=", "10.", "0.0.0/8 ", "172.", "16.0.0/12 ", "192.", "168.0.0/16 ", "100.", "64.0.0/10"), 0),
    (j("a /24 is a network, not the canonical block: ", "10.", "0.0.0/24"), 1),
    (j("glued suffix ", "10.", "0.0.0/8x"), 1),
    (j("a host with a slash ", "10.", "1.0.0/8"), 1),
])
def test_scrub_check_canonical_blocks(text, expect, env):
    r = subprocess.run([SCRUB, "--stdin", "t"], input=text.encode(), capture_output=True, env=env, timeout=30,
                       check=False)
    assert r.returncode == expect, r.stdout.decode()


# The independent review of PR #4 found two false negatives in the JSON-aware scan; these pin the fixes.
@pytest.mark.parametrize("name,payload,expect", [
    ("dup.jsonl", j('{"note":"', BAD_PHONE, '","note":"ok"}'), 1),          # duplicate key hid a value
    ("dup.json", j('{"note":"', BAD_PHONE, '","note":"ok"}'), 1),
    ("diff.jsonl", j('{"diff":"+', BAD_EMAIL, '"}'), 1),                    # an added diff line
    ("deco.jsonl", j('{"diff":"x\\n@pytest', '.fixture\\n+@pytest', '.fixture(scope=\\"module\\")"}'), 0),
])
def test_scrub_check_json_false_negatives(tmp_path, env, name, payload, expect):
    f = tmp_path / name
    f.write_text(payload + "\n")
    r = subprocess.run([SCRUB, "--paths", str(f)], capture_output=True, env=env, timeout=30, check=False)
    assert r.returncode == expect, r.stdout.decode()
