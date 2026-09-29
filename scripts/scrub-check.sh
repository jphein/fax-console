#!/usr/bin/env bash
# scrub-check.sh — refuse to publish identifying data.
#
# Every file in this repo, every commit message and every prompt we hand an AI
# tool must be free of personal, confidential or house-network data (hackathon
# rules §8.6, §8.3). This script is the gate.
#
#   scripts/scrub-check.sh                  scan everything git would publish
#   scripts/scrub-check.sh --staged         scan the staged blobs (pre-commit hook)
#   scripts/scrub-check.sh --message FILE   scan a commit message (commit-msg hook)
#   scripts/scrub-check.sh --paths P...     scan files/dirs (prompts, positive controls)
#   scripts/scrub-check.sh --stdin LABEL    scan text on stdin (the Bob prompt/tool gates)
#   add --require-deny to fail when the private deny-list is missing
#
# Two rule sets:
#   1. GENERIC rules, below. They name no real value, so they are safe to publish:
#      private/CGNAT IPv4, any North-American phone number outside the fictional
#      555-0100..0199 block, non-example e-mail addresses, credential shapes,
#      15-digit IMSI/IMEI shapes.
#   2. A PRIVATE deny-list of real values (the house number, account ids,
#      hostnames, names), read from $FAX_CONSOLE_SCRUB_DENY or
#      ~/.config/fax-console/scrub-deny.txt. It never enters the repo: a checker
#      that lists the secrets it guards publishes them.
#
# Output never prints a match: CI logs of a public repo are public too.
# Exit: 0 clean · 1 findings · 2 usage/config error.
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
# The program travels in a variable, not on stdin: stdin belongs to --stdin callers.
PROG=$(cat <<'PY'
import os, re, subprocess, sys

# Numbers that are PUBLIC test services, used on purpose (documented in BASELINE.md).
ALLOW_NUMBERS = {
    "19725329272",   # Faxbeep, a public fax test receiver (the demo's destination)
    "18884732963",   # HP's public fax test line (named in the legacy route notes)
}
DOC_NETS = (re.compile(r"^192\.0\.2\."), re.compile(r"^198\.51\.100\."), re.compile(r"^203\.0\.113\."))

GENERIC = [
    ("private-ipv4", re.compile(
        r"(?<![\d.])(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
        r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2})(?!\d)(?!\.\d)")),
    ("phone-number", re.compile(
        r"(?<![\d.])(?:\+?1[-. ]?)?\(?([2-9]\d{2})\)?[-. ]?([2-9]\d{2})[-. ]?(\d{4})(?![\d])")),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")),
    ("credential", re.compile(
        r"api_password=[A-Za-z0-9][^&\s\"'<>`]{3,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bghp_[A-Za-z0-9]{20,}"
        r"|\bxox[abprs]-[A-Za-z0-9-]{10,}|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
        r"|\bbob_rt_[0-9a-f]{16,}|\b(?:BOB_API_KEY|VOIPMS_PASS|TELEPHONY_CONSOLE_TOKEN)=[^\s\"'<>*]{6,}")),
    ("imsi-imei-shape", re.compile(r"(?<![\d.])\d{15}(?![\d])")),
]


def allowed(rule, m):
    s = m.group(0)
    if rule == "phone-number":
        digits = re.sub(r"\D", "", s)
        digits = digits if len(digits) == 11 else "1" + digits
        # 555-0100..555-0199: the block reserved for fiction; any area code.
        return digits in ALLOW_NUMBERS or (digits[4:7] == "555" and digits[7:9] == "01")
    if rule == "email":
        dom = m.group(1).lower()
        if re.fullmatch(r"[\d.]+", dom):       # a SIP URI like 2001@192.0.2.10 is not an address
            return True
        return dom in ("example.com", "example.org", "example.net", "anthropic.com", "github.com",
                       "users.noreply.github.com") or dom.endswith(".example")
    if rule == "private-ipv4":
        return any(n.match(s) for n in DOC_NETS)
    return False


def mask(s):
    s = s.strip()
    return s[:2] + "*" * max(1, len(s) - 3) + s[-1:] if len(s) > 3 else "***"


def load_deny(require):
    path = os.environ.get("FAX_CONSOLE_SCRUB_DENY") or os.path.expanduser("~/.config/fax-console/scrub-deny.txt")
    if not os.path.isfile(path):
        msg = f"scrub-check: private deny-list not found ({path}); generic rules only"
        if require:
            print(msg + " -- refusing (--require-deny)", file=sys.stderr)
            sys.exit(2)
        if not os.environ.get("CI"):
            print(msg, file=sys.stderr)
        return []
    rules = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                rules.append((f"deny-list#{i}", re.compile(line)))
            except re.error as e:
                print(f"scrub-check: bad regex on deny-list line {i}: {e}", file=sys.stderr)
                sys.exit(2)
    return rules


def text_of(name, data):
    """Text to scan, or None for a binary we cannot read. PDFs are read via pdftotext:
    a document is exactly where a name and a home address hide."""
    if name.lower().endswith(".pdf"):
        try:
            r = subprocess.run(["pdftotext", "-", "-"], input=data, capture_output=True, timeout=60)
            return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", "replace")


def scan(name, text, rules):
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        for rule, rx in rules:
            for m in rx.finditer(line):
                if not allowed(rule, m):
                    hits.append(f"{name}:{n}: [{rule}] {mask(m.group(0))}")
    return hits


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, check=True).stdout


def main(argv):
    require = "--require-deny" in argv
    argv = [a for a in argv if a != "--require-deny"]
    rules = GENERIC + load_deny(require)
    items, unscanned = [], []
    if not argv:
        names = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").decode().split("\0")
        items = [(p, open(p, "rb").read()) for p in names if p and os.path.isfile(p)]
    elif argv[0] == "--staged":
        names = git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR").decode().split("\0")
        items = [(p, git("show", f":{p}")) for p in names if p]
    elif argv[0] == "--message" and len(argv) == 2:
        items = [("<commit message>", open(argv[1], "rb").read())]
    elif argv[0] == "--stdin" and len(argv) == 2:
        items = [(f"<{argv[1]}>", sys.stdin.buffer.read())]
    elif argv[0] == "--paths" and len(argv) > 1:
        for p in argv[1:]:
            if os.path.isdir(p):
                for d, dirs, fs in os.walk(p):
                    dirs[:] = [x for x in dirs if x not in (".git", "__pycache__", ".venv", "node_modules")]
                    items += [(os.path.join(d, f), open(os.path.join(d, f), "rb").read()) for f in fs]
            else:
                items.append((p, open(p, "rb").read()))
    else:
        print("usage: scrub-check.sh [--staged | --message FILE | --paths P... | --stdin LABEL] [--require-deny]",
              file=sys.stderr)
        return 2
    hits = []
    for name, data in items:
        text = text_of(name, data)
        if text is None:
            unscanned.append(name)
            continue
        hits += scan(name, text, rules)
    for u in unscanned:
        print(f"scrub-check: not scanned (binary): {u}", file=sys.stderr)
    if hits:
        print("\n".join(hits))
        print(f"scrub-check: {len(hits)} finding(s) in {len(items)} item(s) -- NOT clean", file=sys.stderr)
        return 1
    print(f"scrub-check: clean ({len(items)} item(s), {len(rules)} rules)", file=sys.stderr)
    return 0


sys.exit(main(sys.argv[1:]))
PY
)
exec python3 -c "$PROG" "$@"
