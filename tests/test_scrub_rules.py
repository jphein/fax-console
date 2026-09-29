"""Positive and negative controls for the generic rules of scripts/scrub-check.sh (drift-gems).

CI runs only the generic rules (the private deny-list never leaves the workstation), so they are
the whole gate for anything that reaches GitHub without the local hooks. Every rule has text it
must catch and ordinary text (mostly code) it must pass: a rule that silently stops matching, or
starts flagging ordinary code, fails here. Dirty values are assembled at runtime with j(), so
this file passes the scrub itself.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scrub-check.sh"


def j(*parts: str) -> str:
    return "".join(parts)


def scrub(text: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CI": "1", "FAX_CONSOLE_SCRUB_DENY": "/nonexistent/scrub-deny.txt"}
    return subprocess.run(["bash", str(SCRIPT), "--stdin", "t"], input=text, env=env,
                          capture_output=True, text=True, check=False, timeout=60)


CAUGHT = [
    # credentials by shape
    ("credential", j("AKIA", "Z7QX2LMN4PRT8VWY")),
    ("credential", j("AIza", "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q")),
    ("credential", j("sk-ant-", "api03-a1B2c3D4e5F6g7H8")),
    ("credential", j("github_pat_", "11ABCDEFG0123456789_abcdefghij")),
    ("credential", j("ghp_", "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8")),
    ("credential", j("Authorization: Bearer ", "a1B2c3D4e5F6g7H8i9J0k1L2")),
    ("credential", j("PuTTY-User-", "Key-File-3: ssh-ed25519")),
    ("credential", j('{"text": "env\\n', "BOB_API_KEY=", 'abcdef1234567"}')),    # after an escaped \n
    ("credential", j("sk-", "A1b2C3d4E5f6G7h8I9j0K1l2", "M3n4O5p6Q7r8S9t0U1v2W3x4")),   # legacy, 48
    ("credential", j("https://hooks.slack.com/", "services/T0FAKE00/B0FAKE00/",
                     "abcdefghijklmnop")),
    ("credential-assignment", j('api_token = "', 'q7Rf9LmZ2x"')),                         # Aurora's control
    ("credential-assignment", j('password = "', 'testing123"')),                 # a word, not a placeholder
    ("credential-assignment", j('VOIPMS_PASS = "', 'testpassword99"')),          # could be someone's (Aurora)
    ("credential-assignment", j("api_key = '", "yourdomain-9Qx7Lm2Pz'")),
    ("credential-assignment", j("password = ", "123456789")),                    # a number is a value
    ("credential-assignment", j("api_key = '", "test_9Qx7Lm2PzAbC'")),           # a test_ prefix, then a key
    # credential assignments
    ("credential-assignment", j('password="', 'hunter2hunter2"')),
    ("credential-assignment", j("DB_PASSWORD=", "hunter2hunter2")),
    ("credential-assignment", j('"password": "', 's3cr3tpassw0rd"')),
    ("credential-assignment", j("api_token: ", "s3cr3t-t0ken-value")),
    ("credential-assignment", j('self.password = "', 'hunter2hunter"')),
    ("credential-assignment", j("export VOIPMS_", "PASS=", "abcd1234")),
    # house-network shapes
    ("mac-address", j("00:1a:2b", ":3c:4d:5e")),
    ("mac-address", j("00-1A-2B", "-3C-4D-5E")),
    ("lan-hostname", j("ssh nas", ".lan")),
    ("lan-hostname", j("http://pbx.home", ".arpa:8080/")),
    ("lan-hostname", j("gw7.", "internal")),
    ("lan-hostname", j("the printer.", "localdomain.")),
    ("home-path", j("/home/", "alice/projects/fax")),
    ("home-path", j("/Users/", "alice/Desktop")),
    ("ipv6-ula", j("fd", "12:3456:789a::1")),
    ("ipv6-eui64", j("fe80::1a2b:", "3cff:fe4d:5e6f")),
    ("ipv6-eui64", j("2001:2:0:1::21a:2b", "ff:fe3c:4d5e")),    # any prefix (RFC 5180 benchmarking)
    ("email", j("mail alice", "@corp-mail.com")),
    ("email", j('"a\\n', 'alice@', 'corp-mail.com"')),                                  # after an escaped \n
    # subscriber-identity shapes (Aurora's 23:18 rule)
    ("imsi-imei-shape", j("31015", "0123456789")),                                  # an MCC prefix
    ("imsi-imei-shape", j("490154", "20323", "7518")),                                  # a Luhn IMEI
    # a digit run near a commit id is still a number; only a run INSIDE a full id is not (PR #6)
    ("phone-number", j("call ", "202", "555", "0299")),
    ("phone-number", j("fixed in c0ffee1, call ", "202", "555", "0299")),        # an id beside it
    ("phone-number", j("tel", "202", "555", "0299")),                            # glued to a word
    ("phone-number", j("c", "202", "555", "0299", "ab")),                        # abbreviated-id shape
    ("phone-number", j("CAFE", "202", "555", "0299", "BEEF" * 6, "CC")),         # uppercase: no git id
    ("phone-number", j("cafe", "202", "555", "0299", "beef" * 6, "ccc")),        # 41 hex: no git id
    ("phone-number", j("xcafe", "202", "555", "0299", "beef" * 6, "cc")),        # 40 hex glued to a word
    ("imsi-imei-shape", j("ab", "31015", "0123456789", "cdef" * 5, "abcd")),     # 41 hex: no git id
]

PASSED = [
    # ordinary code that names secrets without holding one
    "client = Client(api_key=api_key)",
    "def login(password=password): ...",
    "class Settings: password: SecretStr",
    "password: str | None = None",
    'token = os.environ["BOB_API_KEY"]',
    "password = getpass.getpass()",
    'PATH_TOKEN = re.compile(r"x")',
    "resp = llm(max_tokens=4096)",
    '{"usage": {"input_tokens": 123456, "output_tokens": 7890123}}',          # counts, not secrets
    "PASSWORD_HASH_ITERATIONS = 600000; TOKEN_BUCKET_SIZE = 100000",          # numbers about a secret
    "TOKEN_TTL=604800",
    "bypass=True; compass = north",
    '{"api_key": "***"}',
    "PASSWORD=${PASSWORD}",
    'token_url = "https://auth.example.com/token"',
    "SECRET_FILE=~/.config/fax-console/secret",
    "password = None",
    'write_token = "test-token"; secret = "test-secret-token-abc123"; token = "wrong-token"',  # Bob's fakes
    'token_type = "bearer"; secret_name = "db-password"; password_field = "pw"',               # descriptors
    "AKIAIOSFODNN7EXAMPLE",                                  # AWS's documented example key
    # addresses and names that identify nothing
    "00:00:5e:00:53:01 and ff:ff:ff:ff:ff:ff at 12:34:56",  # RFC 7042 documentation MAC
    "if args.lan and self.internal: pkg.internal.util()",
    "curl http://metadata.google.internal/computeMetadata",
    "x.lan() and a.lan",
    "/home/bob/.bob /home/runner/work /home/linuxbrew/.linuxbrew /home/$(id -un)/.ssh /home/<user>",
    "deny fc00::/7 fd00::/8 fe80::/10 and 2001:db8::1a2b:3cff:fe4d:5e6f",
    "fe80::1 and 2001:db8::1",
    "0xfd12: 3",
    # numbers that only look like numbers of people
    "limits 4294967295 and 2147483647",
    "a made-up 120255501001234",
    "the fictional 202-555-0142",
    # decorators and escapes (Aurora's 23:18 controls)
    "+@pytest.fixture",
    "@pytest.fixture(scope='module')",
    # full git object ids hold digit runs by chance: GitHub's pull_request merge message tripped the
    # phone rule on one (the Oracle, PR #6, 2026-09-29); 40 hex is SHA-1, 64 is SHA-256
    j("Merge cafe", "202", "555", "0299", "beef" * 6, "cc into ", "0123abcd" * 5),
    j("This reverts commit ", "cafe", "202", "555", "0299", "beef" * 6, "cc."),
    j("https://github.com/o/r/commit/", "ab", "31015", "0123456789", "cdef" * 5, "abc"),   # IMSI shape
    j('    "', "cafe", "202", "555", "0299", "beef" * 12, 'cc": "a 64-hex id",'),
]


@pytest.mark.parametrize("rule,text", CAUGHT, ids=[f"{r}-{i}" for i, (r, _) in enumerate(CAUGHT)])
def test_rule_fires(rule, text):
    r = scrub(text)
    assert r.returncode == 1 and f"[{rule}]" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("text", PASSED, ids=range(len(PASSED)))
def test_ordinary_text_passes(text):
    r = scrub(text)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("name,text", [
    ("app.env", j("password=", "hunter22xyz\n")),
    ("settings.ini", j("[db]\npassword = ", "hunterhunter\n")),
    ("app.yaml", j("service:\n  token: ", "abcdef123456ghij\n")),
])
def test_in_config_files_an_unquoted_value_is_a_literal(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding="utf-8")
    env = {**os.environ, "CI": "1", "FAX_CONSOLE_SCRUB_DENY": "/nonexistent/scrub-deny.txt"}
    run = [str(SCRIPT), "--paths", str(tmp_path / name)]
    r = subprocess.run(["bash", *run], env=env, capture_output=True, text=True, check=False, timeout=60)
    assert r.returncode == 1 and "[credential-assignment]" in r.stdout
    (tmp_path / "same.py").write_text(text.replace("[db]\n", ""), encoding="utf-8")   # in code, a name
    r = subprocess.run(["bash", str(SCRIPT), "--paths", str(tmp_path / "same.py")], env=env,
                       capture_output=True, text=True, check=False, timeout=60)
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("line", [
    "a" * 200_000 + "@",                            # the e-mail rule without its look-behind: quadratic
    "a." * 100_000,
    "pass" * 50_000,                                # the assignment rule's key scan
    "ab:" * 66_000,                                 # MAC / IPv6 shapes
    "1" * 200_000,                                  # phone / IMSI shapes
    "x-" * 100_000 + ".lan",
    j("cafe", "202", "555", "0299", "beef" * 6, "cc ") * 5_000,   # every match is inside an id
], ids=["email-run", "dots", "pass", "hex-colons", "digits", "hyphens-lan", "object-ids"])
def test_long_lines_scan_in_linear_time(line):
    t = time.monotonic()
    scrub(line)
    assert time.monotonic() - t < 5.0               # quadratic at 200K characters takes minutes
