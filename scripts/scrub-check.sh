#!/usr/bin/env bash
# scrub-check.sh — refuse to publish identifying data.
#
# Every file in this repo, every commit message and every prompt we hand an AI
# tool must be free of personal, confidential or house-network data (hackathon
# rules §8.6, §8.3). This script is the gate.
#
#   scripts/scrub-check.sh                  scan everything git would publish (contents and file names)
#   scripts/scrub-check.sh --staged         scan the staged blobs and their names (pre-commit hook)
#   scripts/scrub-check.sh --message FILE   scan a commit message (commit-msg hook)
#   scripts/scrub-check.sh --paths P...     scan files/dirs (prompts, positive controls)
#   scripts/scrub-check.sh --stdin LABEL    scan text on stdin (the Bob prompt/tool gates)
#   scripts/scrub-check.sh --shadow         only the stdlib-shadow check, on what is on disk (ignored files
#                                           too): test.sh runs it before the sandbox
#   scripts/scrub-check.sh --history        scan the history this ref publishes (reachable from HEAD):
#                                           every line ever added (merge resolutions included), every
#                                           blob that is not plain text, every file name, every commit
#                                           message and identity, and the annotated tags on it. Other
#                                           branches are gated by their own CI
#   add --require-deny to fail when the private deny-list is missing or has no entries
#
# Two rule sets:
#   1. GENERIC rules, below. They name no real value, so they are safe to publish:
#      private/CGNAT IPv4, IPv6 ULA and EUI-64 addresses, MAC addresses, .lan-style host
#      names, home-directory paths, any North-American phone number outside the fictional
#      555-0100..0199 block, non-example e-mail addresses, credential shapes and assignments,
#      IMSI shapes (a country-code prefix) and IMEI shapes (a Luhn check digit). JSON and JSONL
#      are scanned as their decoded strings.
#   2. A PRIVATE deny-list of real values (the house number, account ids,
#      hostnames, names), read from $FAX_CONSOLE_SCRUB_DENY or
#      ~/.config/fax-console/scrub-deny.txt: one regex per line, matched ignoring case. It never
#      enters the repo: a checker that lists the secrets it guards publishes them.
# Anything that cannot be read as text (a binary, a PDF) is a finding until a person has
# reviewed it and listed its blob id in REVIEWED_BINARIES.
#
# Output never prints a match, or any part of one: only where it is and which rule fired.
# CI logs of a public repo are public too.
# Exit: 0 clean · 1 findings · 2 usage/config error.
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
# The program travels in a variable, not on stdin: stdin belongs to --stdin callers.
PROG=$(cat <<'PY'
import hashlib, json, os, re, subprocess, sys

# Numbers that are PUBLIC test services, used on purpose (documented in BASELINE.md).
ALLOW_NUMBERS = {
    "19725329272",   # Faxbeep, a public fax test receiver (the demo's destination)
    "18884732963",   # HP's public fax test line (named in the legacy route notes)
}
# 32-bit limits look like phone numbers (429-496-7295) and are everywhere in code.
INT_LIMITS = {"4294967295", "4294967296", "2147483647", "2147483648"}
# Anything the gate cannot read as text is a finding until a person has looked at it: a fax page,
# a scan or a photo is exactly where a name hides. That is every binary and every PDF. Text a PDF
# draws as an image or as outlines is invisible to pdftotext, so pdftotext is an extra scan here,
# never a clearance. Review the file by eye, then list its git blob id (`git hash-object FILE`)
# with a note. The id names the exact bytes, so a different file at the same path needs its own
# review. (drift-gems, 2026-09-28; keyed by blob after the independent review of 23:11.)
REVIEWED_BINARIES = {
    # "<40-hex blob id>": "docs/evidence/kpis.png, checked by eye 10/03 by <who>: no names or numbers",
    "537bc885df3b1b3de8fd4448ab8dda1e09724a84": "docs/deck.pdf, checked by eye 2026-09-29 by luna-consulting: "
        "7 slides, dark; no numbers, names, hosts or IPs; unfilled slots show as labels only; "
        "text layer scrub-clean (30 rules)",
    "785d25363dbb43d15bcfd4f1d6dce82c866a9b4e": "docs/deck.pdf (week-2 facts, d663397), checked by eye 2026-09-29 by luna-consulting: "
        "7 slides, dark and light; no numbers, names, hosts or IPs; unfilled slots (demo.url, video.url) show as labels only; "
        "text layer scrub-clean (36 rules)",
    "3c879396e4a1beeeb2c06e3dc7085881c3df91e3": "demo/test-page.pdf, checked by eye 2026-09-29 by luna-consulting: "
        "1 page, neutral text, digits and line pairs; no personal information; text layer scrub-clean (30 rules)",
}
DOC_NETS = (re.compile(r"^192\.0\.2\."), re.compile(r"^198\.51\.100\."), re.compile(r"^203\.0\.113\."))
CANONICAL_BLOCKS = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"}
PUBLIC_HOSTS = {"metadata.google.internal", "host.docker.internal", "gateway.docker.internal"}
# Attribute access that looks like a host name: args.lan, self.internal, cfg.home.arpa.
CODE_RECEIVERS = {"self", "cls", "args", "opts", "options", "cfg", "config", "conf", "settings", "ns",
                  "params", "obj", "this", "ctx", "net", "network", "os", "sys", "np", "a", "o", "p"}
# Home directories that name no person: CI runners, package managers, the sandbox, placeholders.
PUBLIC_HOMES = {"bob", "runner", "linuxbrew", "user", "username", "you", "me", "name", "ubuntu",
                "vscode", "codespace", "example", "shared", "someone"}
SECRET_WORDS = {"pass", "password", "passwd", "passphrase", "pwd", "secret", "token", "tokens", "credential",
                "credentials"}
SECRET_JOINED = ("apikey", "accesskey", "privatekey", "secretkey")
PLACEHOLDER = re.compile(
    r"^(?:<.*>|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|%\(?\w*\)?s|\{\w*\}|x{3,}|\*{3,}|\.{3}|…|changeme"
    # the word, then word-like segments only: test-token, test-password-99, not test_9Qx7Lm2PzAbC
    r"|change[_-]me|(?:example|dummy|fake|test|wrong|bogus|invalid|your)(?:[-_.](?:[a-z]+\d*|\d{1,6}))*"
    r"|none|null|nil|redacted|placeholder"
    r"|false|true|secret|password|token)$", re.IGNORECASE)
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
# A key that ends in one of these describes a secret without holding one: token_type, secret_name.
DESCRIPTORS = {"name", "names", "type", "kind", "id", "ids", "path", "file", "dir", "url", "uri", "header",
               "field", "label", "prefix", "env", "var", "length", "len", "count", "ttl", "expiry", "expires",
               "format", "mode", "scope", "endpoint", "hint", "policy", "version", "source", "store", "backend",
               "iterations", "size", "rounds", "bits", "seconds", "limit"}
# In these files an unquoted value is a literal, however much it looks like a code name.
CONFIG_KINDS = (".env", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".toml", ".properties")
# The owner's commit address, published on every commit (GitHub shows it), kept as a SHA-256 so the gate
# does not spell it out. Any other identity is scanned with every rule, the private list included.
PUBLIC_IDENTITY_SHA256 = {
    "85423212e328e52c9565489a296443f93384a6c4a5b8c905ee61752d89fcd1d9": "the owner's commit address",
}

GENERIC = [
    ("private-ipv4", re.compile(
        r"(?<![\d.])(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
        r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2})(?!\d)(?!\.\d)")),
    ("phone-number", re.compile(
        r"(?<![\d.])(?:\+?1[-. ]?)?\(?([2-9]\d{2})\)?[-. ]?([2-9]\d{2})[-. ]?(\d{4})(?![\d])")),
    # E-mail: see EmailFinder below (linear time; an address after a diff line's "+" is caught).
    ("email", None),
    ("credential", re.compile(
        r"api_password=[A-Za-z0-9][^&\s\"'<>`]{3,}|-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|PuTTY-User-Key-Fil[e]"
        r"|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|\bxox[abprs]-[A-Za-z0-9-]{10,}"
        r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.|\bbob_rt_[0-9a-f]{16,}"
        r"|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_-]{35}|\bsk-(?:ant|proj)-[A-Za-z0-9_-]{16,}"
        r"|\bBearer\s+[A-Za-z0-9._~+/=-]{20,}|\bsk-[A-Za-z0-9]{48}\b"
        r"|https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{20,}"
        # no \b before these names: in a JSON transcript they follow an escaped "\n"
        r"|(?:BOB_API_KEY|VOIPMS_PASS|TELEPHONY_CONSOLE_TOKEN)=(?![$%{<])[^\s\"'<>*\\]{6,}")),
    # key = value where the key names a secret. Which values count is decided in allowed(). The key
    # is matched atomically (a look-ahead capture, then a back-reference: Python 3.10 has no
    # possessive quantifiers), so a long run like "passpass..." costs linear time, not quadratic.
    ("credential-assignment", re.compile(
        r"(?<![A-Za-z0-9_.-])(?=[A-Za-z0-9_.-]*?(?:pass|pwd|secret|token|credential|api[_-]?key|access[_-]?key))"
        r"(?=(?P<key>[A-Za-z0-9_.-]+))(?P=key)"
        r"(?P<op>[\"']?[ \t]*(?::=|=|:)[ \t]*)(?P<q>[\"']?)(?P<v>[^\s\"'`,;(){}\[\]]*)", re.IGNORECASE)),
    ("mac-address", re.compile(
        r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}([:-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:-])")),
    ("lan-hostname", re.compile(
        r"(?<![\w.-])(?P<first>[A-Za-z0-9][A-Za-z0-9-]*)(?:\.[A-Za-z0-9-]+)*"
        r"\.(?:lan|internal|intranet|localdomain|home\.arpa)(?![\w(-]|\.\w)", re.IGNORECASE)),
    ("home-path", re.compile(r"(?<![\w/])/(?:home|Users)/(?P<user>[A-Za-z_][A-Za-z0-9_.-]*)")),
    ("ipv6-ula", re.compile(r"(?<![\w:])f[cd][0-9a-f]{2}:[0-9a-f:]{2,}", re.IGNORECASE)),
    # An EUI-64 interface id (ff:fe in the middle) embeds the machine's MAC, on any prefix.
    ("ipv6-eui64", re.compile(
        r"(?<![\w:])[0-9a-f]{1,4}:[0-9a-f:]*?[0-9a-f]{0,2}ff:fe[0-9a-f]{2}:[0-9a-f]{1,4}(?![\w:])", re.IGNORECASE)),
    ("imsi-imei-shape", re.compile(r"(?<![\d.])\d{15}(?![\d])")),
]


class _Addr:
    """A match-like view of one address: group(0) the address, group(1) its domain."""

    def __init__(self, string, a, b, dom):
        self.string, self._a, self._b, self._dom = string, a, b, dom

    def group(self, i=0):
        return self.string[self._a:self._b] if i == 0 else self._dom

    def start(self):
        return self._a

    def end(self):
        return self._b


class EmailFinder:
    """Addresses, found from each "@" outwards, so a long run of address characters costs linear
    time (a regex that tries every start position took 1.6 s on 40K characters). The local part
    must start with a letter or digit: "+@pytest.fixture" in a diff is a decorator, but the "+"
    that starts an added diff line is not part of the address after it (Aurora, ef817f7)."""
    DOMAIN = re.compile(r"@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
    LOCAL = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._%+-")
    ALNUM = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")

    def finditer(self, line):
        floor = 0
        for m in self.DOMAIN.finditer(line):
            i = m.start()
            while i > floor and line[i - 1] in self.LOCAL:
                i -= 1
            while i < m.start() and line[i] not in self.ALNUM:
                i += 1
            floor = m.end()                      # the next address starts after this one
            if i < m.start():
                yield _Addr(line, i, m.end(), m.group(1))


GENERIC = [(name, rx if rx is not None else EmailFinder()) for name, rx in GENERIC]


def key_words(key):
    k = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)          # camelCase -> camel_Case
    parts = [p.lower() for p in re.split(r"[_.\-]+", k) if p]
    return parts, "".join(parts)


def is_config(kind):
    base = os.path.basename(kind.lower())
    return base.endswith(CONFIG_KINDS) or base.startswith(".env")


def secret_value(m, kind=""):
    """True when a `key = value` names a secret and the value looks like one."""
    key, quoted, v = m.group("key"), m.group("q"), m.group("v")
    parts, joined = key_words(key)
    if not (SECRET_WORDS.intersection(parts) or any(s in joined for s in SECRET_JOINED)):
        return False                                   # compass=, bypass=, max_tokens=
    if parts and parts[-1] in DESCRIPTORS:
        return False                                   # token_type = "bearer": about a secret, not one
    if v.isdigit() and not (parts[-1] in SECRET_WORDS - {"tokens"} or joined.endswith(SECRET_JOINED)):
        return False                                   # a number is a secret only under a secret's own name
    if (len(v) < 6 or PLACEHOLDER.match(v) or re.match(r"[a-z][a-z0-9+.-]*://", v)
            or v.startswith(("/", "~/", "./", "../"))):
        return False                                   # a flag, a placeholder, a URL, a path
    if quoted:
        return True                                    # a quoted literal is a value, whatever it says
    if m.string[m.end():m.end() + 1] in ("(", "["):
        return False                                   # a call or a subscript: code
    if (key == key.upper() and not re.search(r"[ \t]", m.group("op"))) or is_config(kind):
        return not v.startswith(("$", "%"))            # DB_PASSWORD=..., or any .env/.ini/.yaml value
    # Code: password=password, token=self.token, password: SecretStr, TOKEN_RX = re.compile(...)
    return not IDENT.match(v)


HEX = frozenset("0123456789abcdef")
# Full hex ids: 32 = Bob Shell's task_id (every docs/bob-runs transcript carries one) and MD5,
# 40 = a SHA-1 git object id, 64 = a SHA-256 one.
ID_LENGTHS = (32, 40, 64)
AGENT_ID_LEN = 17          # this team's agent ids: "a" and 16 lowercase hex


def in_object_id(m):
    """True if the match is digits inside a full hex id: 32, 40 or 64 lowercase hex characters,
    at least one of them a letter, with no letter, digit or underscore on either side.
    GitHub's pull_request merge message ("Merge <40 hex> into <40 hex>") tripped the phone rule
    on a 10-digit run inside the head's id (the Oracle, PR #6, 2026-09-29). A revert message
    ("This reverts commit <40 hex>"), a blob id in REVIEWED_BINARIES or a Bob transcript's
    32-hex task_id can do the same (the Oracle: a few percent of runs).
    Abbreviated ids are not exempt: a 10-12 character one could be a phone number with two hex
    letters glued on, and git abbreviates this repo's ids to 7, too short for 10 digits.
    Uppercase hex, any other length, or a run glued to a word stays a finding."""
    s, a, b = m.string, m.start(), m.end()
    if not all(c in HEX for c in s[a:b]):
        return False
    lo, hi = a, b
    while lo > 0 and s[lo - 1] in HEX and b - lo < 65:   # bounded: a longer run is no id anyway
        lo -= 1
    while hi < len(s) and s[hi] in HEX and hi - lo < 65:
        hi += 1
    def word(c):
        return c.isalnum() or c == "_"
    return (hi - lo in ID_LENGTHS and any(c in "abcdef" for c in s[lo:hi])
            and not (lo > 0 and word(s[lo - 1])) and not (hi < len(s) and word(s[hi])))


def in_agent_id(m):
    """True if the match is digits inside one of this team's agent ids: exactly "a" and 16 lowercase hex
    characters, with no letter, digit or underscore on either side. Reviews cite them, and a PR squash
    message tripped the phone rule on a 10-digit run inside one (#17, 2026-09-29). Only that exact shape
    is exempt, so in_object_id's findings all stand: an abbreviated id, a run glued to a word, and any
    other length or first letter. The private deny-list still catches a real number in any context."""
    s, a, b = m.string, m.start(), m.end()
    if not all(c in HEX for c in s[a:b]):
        return False
    lo, hi = a, b
    while lo > 0 and s[lo - 1] in HEX and b - lo <= AGENT_ID_LEN:   # bounded: stop one past an id
        lo -= 1
    while hi < len(s) and s[hi] in HEX and hi - lo <= AGENT_ID_LEN:
        hi += 1
    def word(c):
        return c.isalnum() or c == "_"
    return (hi - lo == AGENT_ID_LEN and s[lo] == "a"
            and not (lo > 0 and word(s[lo - 1])) and not (hi < len(s) and word(s[hi])))


def allowed(rule, m, kind=""):
    s = m.group(0)
    if rule in ("phone-number", "imsi-imei-shape") and (in_object_id(m) or in_agent_id(m)):
        return True                                    # digits inside a commit or blob id, or an agent id
    if rule == "phone-number":
        raw = re.sub(r"\D", "", s)
        digits = raw if len(raw) == 11 else "1" + raw
        # 555-0100..555-0199: the block reserved for fiction; any area code.
        return (digits in ALLOW_NUMBERS or raw in INT_LIMITS
                or (digits[4:7] == "555" and digits[7:9] == "01"))
    if rule == "email":
        dom = m.group(1).lower()
        if re.fullmatch(r"[\d.]+", dom):       # a SIP URI like 2001@192.0.2.10 is not an address
            return True
        return dom in ("example.com", "example.org", "example.net", "anthropic.com", "github.com",
                       "users.noreply.github.com") or dom.endswith(".example")
    if rule == "imsi-imei-shape":
        # 15 digits alone name no subscriber. Flag the shapes that can: an IMSI starts with a mobile
        # country code (2xx-7xx, 9xx for international/test networks, 001 for test), and an IMEI
        # carries a valid Luhn check digit. A made-up "too long" number like 1202555010012xx is neither.
        return not (s[0] in "2345679" or s.startswith("001") or luhn_ok(s))
    if rule == "private-ipv4":
        # A whole private range in canonical CIDR form (a firewall rule, a sandbox deny list)
        # names no host, so it cannot leak one: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10.
        pfx = re.match(r"/(\d{1,2})(?![\d\w])", m.string[m.end():])
        if pfx and f"{s}/{pfx.group(1)}" in CANONICAL_BLOCKS:
            return True
        return any(n.match(s) for n in DOC_NETS)
    if rule == "credential":
        return s.startswith(("AKIA", "ASIA")) and s.endswith("EXAMPLE")   # AWS's documented example
    if rule == "credential-assignment":
        return not secret_value(m, kind)
    if rule == "mac-address":
        v = s.lower().replace("-", ":")
        return (v in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff")
                or v.startswith(("00:00:5e:00:53:", "01:00:5e:90:10:")))    # RFC 7042 documentation
    if rule == "lan-hostname":
        return m.group("first").lower() in CODE_RECEIVERS or s.lower() in PUBLIC_HOSTS
    if rule == "home-path":
        return m.group("user").lower() in PUBLIC_HOMES
    if rule == "ipv6-eui64":
        return s.lower().startswith("2001:db8:")                             # RFC 3849 documentation
    return False


def luhn_ok(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


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
                # Ignoring case: the same name typed in capitals is the same leak.
                rules.append((f"deny-list#{i}", re.compile(line, re.IGNORECASE)))
            except re.error as e:
                print(f"scrub-check: bad regex on deny-list line {i}: {e.msg}", file=sys.stderr)
                sys.exit(2)
    if not rules:
        msg = f"scrub-check: the private deny-list has no entries ({path})"
        if require:
            print(msg + " -- refusing (--require-deny)", file=sys.stderr)
            sys.exit(2)
        print(msg + "; generic rules only", file=sys.stderr)
    return rules


def blob_id(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def is_pdf(name, data):
    return name.lower().endswith(".pdf") or data[:5] == b"%PDF-"


def text_of(name, data):
    """Text to scan, or None for content that cannot be read as text."""
    if is_pdf(name, data):
        try:
            r = subprocess.run(["pdftotext", "-", "-"], input=data, capture_output=True, timeout=60)
            return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None
    for bom, enc in ((b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"),
                     (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if data.startswith(bom):          # UTF-16/32 text is text: decode it, then scan it
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                return None
    if b"\0" in data:
        return None
    return data.decode("utf-8", "replace")


class _Pairs(list):
    """A JSON object as its raw (key, value) pairs: json.loads would keep only the LAST of two
    duplicate keys, so a value could hide behind a later copy of its key (Aurora, ef817f7)."""


def json_strings(obj):
    """Every key and value, and each member with a scalar value also as `key: "value"`, so a rule
    about a key and its value (a password, an API key) sees them together."""
    if isinstance(obj, (_Pairs, dict)):
        for k, v in (obj if isinstance(obj, _Pairs) else obj.items()):
            yield str(k)
            for item in (v if isinstance(v, list) else [v]):
                if isinstance(item, (str, int, float, bool)):
                    yield f'{k}: "{item}"'
            yield from json_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from json_strings(v)
    elif obj is not None:
        yield str(obj)


def lines_of(kind, text):
    """(where, line) pairs to scan. JSON escapes hide what a value really says (an escaped newline
    followed by a Python decorator reads as an e-mail address), so .json and .jsonl content is
    scanned as its decoded strings (Aurora, 9/28 23:18). A JSONL finding keeps its file line; a
    .json finding names the decoded string's index. Anything that does not decode is scanned raw."""
    kind = kind.lower()
    if kind.endswith(".jsonl"):
        for n, raw in enumerate(text.split("\n"), 1):
            try:
                strings = list(json_strings(json.loads(raw, object_pairs_hook=_Pairs)))
            except ValueError:
                strings = [raw]
            for s in strings:
                for sub in s.splitlines():
                    yield str(n), sub
        return
    if kind.endswith(".json"):
        try:
            strings = list(json_strings(json.loads(text, object_pairs_hook=_Pairs)))
        except ValueError:
            strings = None
        if strings is not None:
            for n, s in enumerate(strings, 1):
                for sub in s.splitlines():
                    yield f"json-string-{n}", sub
            return
    for n, line in enumerate(text.splitlines(), 1):
        yield str(n), line


# The end of one string literal and the start of the next, `", "`, `" + '`, `" b"`, across newlines too.
LITERAL_JOIN = re.compile(r"""["']\s*[,+]?\s*(?:[bBrRuUfF]{1,2})?["']""")


def scan(name, text, rules, kind=""):
    """Findings for each line. The private rules also read the line with adjacent string literals
    joined: a test vector split across string literals with j() is invisible to a regex, but a
    vector must never be a real value, so a private hit there is always a leak (PR #2, 9/29 00:15)."""
    hits, private, kind = [], [r for r in rules if r[0].startswith("deny-list#")], kind or name
    for where, line in lines_of(kind, text):
        views = [(line, rules)]
        joined = LITERAL_JOIN.sub("", line) if private else line
        if joined != line:
            views.append((joined, private))
        for view, view_rules in views:
            for rule, rx in view_rules:
                hit = f"{name}:{where}: [{rule}]"        # where and which rule; never the value
                if hit not in hits and any(not allowed(rule, m, kind) for m in rx.finditer(view)):
                    hits.append(hit)
    if private:                                          # a split a formatter wrapped over lines
        whole = LITERAL_JOIN.sub("", text)
        if whole != text:
            for rule, rx in private:
                if not any(h.endswith(f"[{rule}]") for h in hits) and rx.search(whole):
                    hits.append(f"{name}:joined: [{rule}]")
    return hits


def check(label, path, data, rules):
    """Findings for one item. `path` is None for text that has no file behind it (a message, a
    prompt, a file name, lines taken from a diff); otherwise every PDF and every binary needs a
    person's review, keyed by blob id, and whatever text can be read is scanned as well."""
    if path is None:
        if b"\0" in data:
            return [f"{label}: [unreadable-text]"]
        return scan(label, data.decode("utf-8", "replace"), rules, label.strip("<>"))
    text, hits = text_of(path, data), []
    if text is None or is_pdf(path, data):
        bid = blob_id(data)
        if bid not in REVIEWED_BINARIES:
            kind = os.path.splitext(path)[1].lower() or "binary"
            hits.append(f"{label}: [binary-needs-review] {kind} blob {bid}")
    if text is not None:
        hits += scan(label, text, rules, path)
    return hits


def git(*a):
    return subprocess.run(["git", "-c", "core.quotePath=false", *a], capture_output=True, check=True).stdout


def cat_objects(ids):
    """{id: raw object bytes} through one `git cat-file --batch`: robust to any byte in a message."""
    if not ids:
        return {}
    out = subprocess.run(["git", "cat-file", "--batch"], input="".join(i + "\n" for i in ids).encode(),
                         capture_output=True, check=True).stdout
    objs, pos = {}, 0
    for i in ids:
        nl = out.index(b"\n", pos)
        size = int(out[pos:nl].split()[2])
        objs[i] = out[nl + 1:nl + 1 + size]
        pos = nl + 1 + size + 1
    return objs


IDENT_LINE = re.compile(rb"^(author|committer|tagger) (.*?) <([^>]*)> \d+ [+-]\d{4}$")
LOCAL_DOMAINS = (".local", ".lan", ".localdomain", ".home.arpa", ".internal", "(none)")


def identities(label, raw, rules):
    """Commit and tag identities. The owner's address is published by design (GitHub shows it on
    every commit), so the e-mail rule and the private list skip it, and only it. Every address is
    checked for the machine-local host an unconfigured `user.email` leaks."""
    hits = []
    addr_rules = [r for r in rules if r[0] != "email" and not r[0].startswith("deny-list#")]
    for line in raw.split(b"\n\n", 1)[0].split(b"\n"):
        m = IDENT_LINE.match(line)
        if not m:
            continue
        kind, name, email = (g.decode("utf-8", "replace") for g in m.groups())
        hits += scan(f"{label}:<{kind} name>", name, rules)
        owner = hashlib.sha256(email.strip().lower().encode()).hexdigest() in PUBLIC_IDENTITY_SHA256
        hits += scan(f"{label}:<{kind} e-mail>", email, addr_rules if owner else rules)
        dom = email.rpartition("@")[2].lower()
        if "." not in dom or dom.endswith(LOCAL_DOMAINS):
            hits.append(f"{label}:<{kind} e-mail>: [machine-local-identity]")
    return hits


def history(rules, rev="HEAD"):
    """Everything `rev` publishes, as (label, path, data) items plus identity findings."""
    items, hits = [], []
    # 1. Every added line, at its real line number. Hunk lengths are counted, so an added line
    #    that itself starts with "++ " is content, not a file header. Merges are diffed against
    #    their first parent, so a resolution that only a merge commit adds is scanned too.
    log = git("log", rev, "-p", "--no-color", "--no-ext-diff", "--no-textconv", "--unified=0", "--no-renames",
              "--diff-merges=first-parent", "--format=%x00%h").decode("utf-8", "replace")
    as_binary = set()     # (commit, path) git showed as "Binary files ... differ": .gitattributes can say so
    sha = path = "?"
    lineno = rem_old = rem_new = 0
    added = {}    # (commit, path) -> {new-file line number: text}
    for line in log.split("\n"):
        if rem_old or rem_new:
            if line.startswith("+") and rem_new:
                rem_new -= 1
                lineno += 1
                added.setdefault((sha, path), {})[lineno] = line[1:]
                continue
            if line.startswith("-") and rem_old:
                rem_old -= 1
                continue
            if line.startswith("\\"):
                continue
            rem_old = rem_new = 0                          # malformed: read it as a header line
        if line.startswith("\0"):
            sha = line[1:]
        elif line.startswith("Binary files ") and line.endswith(" differ"):
            b = re.search(r" and (?:b/)?(.+) differ$", line)
            if b and b.group(1) != "/dev/null":
                as_binary.add((sha[:7], b.group(1)))
        elif line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("@@ "):
            h = re.match(r"@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if h:
                rem_old = int(h.group(1)) if h.group(1) is not None else 1
                rem_new = int(h.group(3)) if h.group(3) is not None else 1
                lineno = int(h.group(2)) - 1
    added_at = {(c[:7], pth) for c, pth in added}     # where step 1 saw lines; a quoted name is not here
    for (c, pth), lines in added.items():
        if pth.lower().endswith(".json"):
            continue                                        # fragments of JSON: see step 2
        text = "\n".join(lines.get(i, "") for i in range(1, max(lines) + 1))
        items.append((f"{c}:{pth}", None, text.encode()))
    # 2. Every blob version that is not plain text (and every .json version, decoded whole), and
    #    every file name. The -z raw listing is a stream of NUL-terminated tokens: a commit id,
    #    then ":meta" and path pairs.
    toks = git("log", rev, "--raw", "--no-abbrev", "--no-renames", "--diff-merges=first-parent", "-z",
               "--format=%x00%x00%h").split(b"\0")
    blobs, names, c, i = {}, set(), "?", 0
    while i < len(toks):
        t = toks[i].lstrip(b"\n")
        if t.startswith(b":") and i + 1 < len(toks):
            meta, p = t.decode().split(), toks[i + 1].decode("utf-8", "replace")
            names.add(p)
            if len(meta) >= 5 and not meta[4].startswith("D") and meta[1] != "160000":
                unseen = (c, p) in as_binary or (c, p) not in added_at
                blobs.setdefault(meta[3], (f"{c}:{p}", p, unseen))   # not deleted, not a submodule
            i += 2
            continue
        if t:
            c = t.decode()[:7]
        i += 1
    objs = cat_objects(list(blobs))
    for bid, (label, p, shown_binary) in blobs.items():
        if (shown_binary or text_of(p, objs[bid]) is None or is_pdf(p, objs[bid])
                or p.lower().endswith(".json")):
            items.append((label, p, objs[bid]))                    # other text: step 1 has it
    items += [(f"<file name> {n}", None, n.encode()) for n in sorted(names)]
    # 3. Every commit message and identity, and every tag on this history.
    commits = git("rev-list", rev).decode().split()
    objs = cat_objects(commits)
    for c in commits:
        body = objs[c].split(b"\n\n", 1)[1] if b"\n\n" in objs[c] else b""
        items.append((f"{c[:7]}:<commit message>", None, body))
        hits += identities(c[:7], objs[c], rules)
    reach = set(commits)
    fmt = "%(objectname) %(objecttype) %(*objectname) %(refname:short)"
    for line in git("for-each-ref", "refs/tags", f"--format={fmt}").decode().splitlines():
        oid, typ, target, tag = (line.split(" ", 3) + ["", "", ""])[:4]
        if (target if typ == "tag" else oid) not in reach:
            continue
        items.append((f"<tag name> {tag}", None, tag.encode()))
        if typ == "tag":
            raw = cat_objects([oid])[oid]
            items.append((f"tag {tag}:<message>", None, raw.split(b"\n\n", 1)[1] if b"\n\n" in raw else b""))
            hits += identities(f"tag {tag}", raw, rules)
    return items, hits


STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"sitecustomize", "usercustomize"}
PATH_DIRS = ("", "tests", "scripts")      # the repo root (python -c/-m), and where pytest and scripts run


def module_of(fname):
    """The module a file in a sys.path directory provides, or None. That is json.py, a sourceless
    json.pyc (imported when no json.py sits beside it), or an extension: json.so,
    json.abi3.so or json.cpython-314-x86_64-linux-gnu.so."""
    if fname.endswith((".py", ".pyc")):
        return fname.rsplit(".", 1)[0]
    if fname.endswith(".so"):
        return fname.split(".", 1)[0]
    return None


def shadow_findings(paths):
    """A module or package named like a standard-library one, in a directory Python puts first on
    sys.path, is imported instead of the real one by the next tool that runs there. A planted json.py
    at the repo root would run on the host or fake a clean CI (the Oracle, 9/29 01:40). So would a
    sourceless json.pyc, which .gitignore can hide (the Oracle via Aurora, PR #8), and so would a
    json.so."""
    hits = []
    for p in paths:
        parts = p.split("/")
        if "/".join(parts[:-1]) in PATH_DIRS and (module_of(parts[-1]) in STDLIB or parts[-1] in STDLIB):
            # the bare name too: a symlink named json that points at a package directory is imported as
            # json, and git lists it as the path "json", not as a directory (the Oracle, PR #9)
            hits.append(f"{p}: [stdlib-shadow]")
        elif (len(parts) >= 2 and module_of(parts[-1]) == "__init__" and "/".join(parts[:-2]) in PATH_DIRS
              and parts[-2] in STDLIB):
            hits.append(f"{p}: [stdlib-shadow]")
    return hits


def disk_shadow_paths():
    """What is on disk in the sys.path directories, ignored files too, and the findings for what could
    not be listed. Python imports what is there, not what git tracks, so a json.pyc hidden by .gitignore
    must still be seen. Package directories are listed through their __init__ file.

    A directory that cannot be listed is a finding, never skipped. Python imports json/__init__.py by
    path through a directory it may not list (mode 0311), so skipping it read a planted package as clean
    (Aurora's audit, after #21). Only an absent one is skipped: a repo without tests/ has none to import."""
    out, unlistable = [], []
    for d in PATH_DIRS:
        try:
            entries = sorted(os.listdir(d or "."))
        except FileNotFoundError:
            continue
        except OSError:
            unlistable.append(f"{d or '.'}/: [unlistable]")
            continue
        for e in entries:
            p = f"{d}/{e}" if d else e
            if os.path.isdir(p) and not os.path.islink(p):
                try:
                    out += [f"{p}/{f}" for f in sorted(os.listdir(p)) if module_of(f) == "__init__"]
                except FileNotFoundError:
                    pass
                except OSError:
                    unlistable.append(f"{p}/: [unlistable]")
            else:
                out.append(p)
    return out, unlistable


def masked(hit, rules):
    """A finding's location with any matched value in it (a file or tag name) replaced by ***."""
    where, sep, what = hit.rpartition(": [")
    if not sep:
        return hit
    spans = sorted((m.start(), m.end()) for rule, rx in rules for m in rx.finditer(where)
                   if not allowed(rule, m, where))
    merged = []
    for a, b in spans:                                   # overlapping matches become one span
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    for a, b in reversed(merged):
        where = where[:a] + "***" + where[b:]
    return where + sep + what


def main(argv):
    require = "--require-deny" in argv
    argv = [a for a in argv if a != "--require-deny"]
    rules = GENERIC + load_deny(require)
    items, hits = [], []
    if not argv:
        names = [p for p in git("ls-files", "-z", "--cached", "--others", "--exclude-standard").decode().split("\0")
                 if p and os.path.isfile(p)]
        items = [(p, p, open(p, "rb").read()) for p in names]
        items += [(f"<file name> {p}", None, p.encode()) for p in names]
        on_disk, unlistable = disk_shadow_paths()
        hits += unlistable + shadow_findings(sorted(set(names) | set(on_disk)))
    elif argv[0] == "--staged":
        names = [p for p in git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT").decode().split("\0")
                 if p]
        items = [(p, p, git("cat-file", "blob", f":{p}")) for p in names]
        items += [(f"<file name> {p}", None, p.encode()) for p in names]
        hits += shadow_findings(names)
    elif argv[0] == "--shadow" and len(argv) == 1:
        # A planted json.py, json.pyc, json.so, json/ package or json symlink at the root, in tests/ or in
        # scripts/ is imported instead of the real module, so one file could fake a green test run. Every
        # bypass of the Bob guard ends in such a file, and test.sh refuses to run while one is on disk
        # (the Oracle's delta on PR 11).
        on_disk, unlistable = disk_shadow_paths()
        hits += unlistable + shadow_findings(on_disk)
    elif argv[0] == "--message" and len(argv) == 2:
        items = [("<commit message>", None, open(argv[1], "rb").read())]
    elif argv[0] == "--stdin" and len(argv) == 2:
        items = [(f"<{argv[1]}>", None, sys.stdin.buffer.read())]
    elif argv[0] == "--history" and len(argv) in (1, 2):
        rev = argv[1] if len(argv) == 2 else "HEAD"
        try:
            rev = git("rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}").decode().strip()
        except subprocess.CalledProcessError:
            print(f"scrub-check: not a commit: {rev}", file=sys.stderr)
            return 2
        items, hits = history(rules, rev)
    elif argv[0] == "--paths" and len(argv) > 1:
        # What the gate cannot read it cannot clear. os.walk skipped a directory it could not list, silently,
        # and a file it could not open ended the scan with a traceback. Each is a finding now (Aurora's
        # Oracle, after #21).
        def unlistable(err):
            hits.append(f"{err.filename}/: [unlistable]")

        def add(path):
            try:
                items.append((path, path, open(path, "rb").read()))
            except OSError:
                hits.append(f"{path}: [unreadable]")

        for p in argv[1:]:
            if os.path.isdir(p):
                for d, dirs, fs in os.walk(p, onerror=unlistable):
                    dirs[:] = [x for x in dirs if x not in (".git", "__pycache__", ".venv", "node_modules")]
                    for f in fs:
                        add(os.path.join(d, f))
            else:
                add(p)
    else:
        print("usage: scrub-check.sh [--staged | --message FILE | --paths P... | --stdin LABEL | --history [REV]"
              " | --shadow]"
              " [--require-deny]",
              file=sys.stderr)
        return 2
    for label, path, data in items:
        hits += check(label, path, data, rules)
    if hits:
        print("\n".join(masked(h, rules) for h in hits))
        print(f"scrub-check: {len(hits)} finding(s) in {len(items)} item(s) -- NOT clean", file=sys.stderr)
        return 1
    print(f"scrub-check: clean ({len(items)} item(s), {len(rules)} rules)", file=sys.stderr)
    return 0


sys.exit(main(sys.argv[1:]))
PY
)
# -I (isolated): the current directory is the repo root, which Bob can write; a json.py there must
# not be imported by the gate, here or in the hooks and CI that run it.
exec python3 -I -c "$PROG" "$@"
