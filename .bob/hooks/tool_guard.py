#!/usr/bin/env python3
"""Bob PreToolUse hook: keep Bob inside the repo, off the network, and away from the PBX.

This repository modernizes a live house fax/PBX service, but nothing here may
touch it. The rules this hook enforces, each for a stated reason:

  * no network or remote commands (ssh, scp, curl, gh, git push, pip install ...):
    the legacy code ssh-es to a PBX, and the project must never reach one;
  * no privileged or PBX commands (sudo, asterisk, the real `fax` CLI);
  * no paths outside the workspace: private material lives outside it by design;
  * no writes to the frozen baseline (legacy/, BASELINE.md, LICENSE), to .git/, or to
    the guard and its rules (.bob/, scripts/, AGENTS.md): an agent must not be able
    to loosen its own sandbox;
  * no write whose content carries identifying data (the scrub-check rules);
  * no web or MCP tools: this work needs neither.

It FAILS CLOSED: Bob treats a crashed hook as "allow", so any unexpected error
becomes a deny (exit 2).
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Inside scripts/bob-sandbox.sh the private deny-list is deliberately invisible, so these hooks use the
# generic rules there; the private list is applied outside, to every prompt before it is sent and to
# every commit. Outside the sandbox a missing list is a refusal, as before.
SANDBOXED = os.environ.get("FAX_CONSOLE_SANDBOX") == "1"
REQUIRE = [] if SANDBOXED else ["--require-deny"]
LOG = os.environ.get("FAX_CONSOLE_GUARD_LOG") or os.path.join(ROOT, ".bob", "guard.log")

DENY_TOOLS = re.compile(r"web_fetch|web_search|browser|mcp|use_skill", re.IGNORECASE)
DENY_COMMAND = re.compile(
    r"(?:^|[\s;&|()`$])(?:ssh|scp|sftp|rsync|curl|wget|nc|ncat|telnet|ftp|sudo|su|doas|gh|asterisk|fax|"
    r"systemctl|docker|podman|apt|apt-get|dpkg|snap|npm|npx|pnpm|yarn|brew|pipx|bob|bobide)(?=$|[\s;&|()`])"
    # git: read-only subcommands only, and no options before the subcommand (`git -c core.pager=…`
    # or `-C dir` would run a command or leave the repo). The sandbox's read-only .git is the real
    # control; this refusal just says so early. (`git stash` reached the sandbox once and failed there.)
    r"|\bgit\s+-"
    r"|\bgit\s+(?!(?:status|diff|log|show|blame|ls-files|ls-tree|rev-parse|grep|shortlog|describe"
    r"|cat-file)\b)\S"
    r"|\bpip3?\s+(?:install|download)\b|\bpython3?\s+-m\s+pip\s+(?:install|download)\b"
    r"|\buv\s+(?:pip|add|sync|run)\b|/dev/tcp/|\bsocket\.|\burllib\.request|\bhttp\.client|\brequests\.",
    re.IGNORECASE)
# Running the legacy code or the new CLI for real would make IT reach the PBX (it shells out to ssh),
# out of this guard's sight. Behaviour is exercised through pytest with mocked I/O instead.
# Only the COMMAND POSITION of each shell segment counts: `grep x legacy/f.py` reads, it does not run.
LEGACY_EXE = re.compile(r"^(?:\./)?legacy/\S*(?:bin/fax|\.py)$")
INTERPRETERS = {"python", "python3", "bash", "sh", "exec", "env", "nohup", "timeout", "xargs"}
SAFE_MODULES = {"py_compile", "compileall", "ast", "pytest", "ruff", "tokenize", "pyclbr"}


def runs_live_code(cmd):
    for seg in re.split(r"&&|\|\||[;&|\n]|\$\(|`", cmd):
        words = [w.strip("'\"") for w in seg.split()]
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):   # leading VAR=value
            words.pop(0)
        if not words:
            continue
        exe = words[0]
        if LEGACY_EXE.match(exe):
            return True
        if os.path.basename(exe) in ("fax", "faxcli", "fax-console") and len(words) > 1 \
                and words[1] in ("send", "status", "log", "test", "inbox", "serve"):
            return True
        base = os.path.basename(exe)
        if base.rstrip("0123456789.") in INTERPRETERS or base.startswith("python"):
            rest = words[1:]
            if "-m" in rest:
                k = rest.index("-m")
                mod = rest[k + 1] if k + 1 < len(rest) else ""
                if mod.split(".")[0] in ("faxcli", "faxconsole"):
                    return True
                if mod.split(".")[0] in SAFE_MODULES:
                    continue
            target = next((w for w in rest if not w.startswith("-")), "")
            if target.startswith(("legacy/", "./legacy/")):
                return True
    return False
# Path-like tokens in a command line: absolute, home-relative, or climbing out with "..".
PATH_TOKEN = re.compile(r"(?:(?<=^)|(?<=[\s='\"(:]))"
                        r"(~[^\s'\";&|)]*|\$HOME[^\s'\";&|)]*|/[^\s'\";&|)]*|\.\.(?:/[^\s'\";&|)]*)?)")
SYSTEM_OK = ("/usr/", "/bin/", "/dev/null")      # interpreters and the bit bucket
PROTECTED = ("legacy/", ".git/", ".bob/", "scripts/", "AGENTS.md", "BASELINE.md", "LICENSE")
WRITE_TOOL = re.compile(r"write|apply|insert|replace|edit|delete|remove|move|rename|create|patch",
                        re.IGNORECASE)
PATH_KEYS = ("path", "file_path", "filepath", "target_file", "file", "paths", "files", "target",
             "destination",
             "source", "directory", "dir", "cwd")
CONTENT_KEYS = ("content", "contents", "diff", "patch", "new_str", "new_string", "text", "replace",
                "replacement",
                "new_content", "code", "search_and_replace", "edits", "operations", "lines")


def log(verdict, tool, detail):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            rec = {"hook": "tool_guard", "verdict": verdict, "tool": tool, "detail": detail[:300]}
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


MARKER = "sandbox guard: "   # on every refusal: scripts/redact-refused.py keys on it (the review of PR 8)


def deny(tool, reason):
    reason = MARKER + reason
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    print(reason, file=sys.stderr)
    log("deny", tool, reason)
    sys.exit(2)


def strings(obj, keys=None):
    """Every string value under the given keys (any depth); all strings if keys is None."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if keys is None or k.lower() in keys:
                out += strings(v, None)
            elif isinstance(v, (dict, list)):
                out += strings(v, keys)
    elif isinstance(obj, list):
        for v in obj:
            out += strings(v, keys)
    elif isinstance(obj, str):
        out.append(obj)
    return out


# A module named like the standard library, at the repo root or in tests/ or scripts/, shadows the stdlib
# for any `python3 -c` or `python3 -` run from the root: the host-side wrapper and the hooks would import
# it (the independent review, 9/29 01:40). Refused for write tools and for command tokens alike.
STDLIB = frozenset(sys.stdlib_module_names)
SHADOW_DIRS = ("", "tests", "scripts")


def shadows_stdlib(rel):
    """True for a stdlib-named .py file or package directly at the root, in tests/ or in scripts/."""
    parts = rel.replace("\\", "/").lstrip("./").split("/")
    for depth in (1, 2):                                   # json.py | tests/re.py | json/__init__.py
        if len(parts) < depth:
            continue
        head, name = "/".join(parts[:depth - 1]), parts[depth - 1]
        if head not in SHADOW_DIRS:
            continue
        stem = (name[:-3] if name.endswith(".py") else name[:-4] if name.endswith(".pyc")
                else (name if len(parts) > depth else None))
        if stem and stem in STDLIB:
            return True
    return False


# A token starts at a path boundary: never right after "/" or ".", or "faxcli/numbers.py" would read as
# a root-level numbers.py.
SHADOW_TOKEN = re.compile(r"(?<![\w./-])((?:\./)?(?:tests/|scripts/)?[A-Za-z_][\w]*(?:\.pyc?|/__init__\.py))")
# Only a command that can create or rename a file is checked. A read such as `grep numbers.py docs/x.md`
# is not
# (the review of PR 8 found that false positive).
# A path prefix or a backslash before the name still counts (the Oracle's delta on PR 8: /usr/bin/cp, \\cp).
WRITES = re.compile(r"(?:^|[\s;&|(])\\?(?:[\w./-]*/)?"
                    r"(?:cp|mv|install|ln|touch|tee|dd|rsync|tar|unzip|git|python3?|sed)\b|>")
# Bob's own configuration: a gateway planted in its settings would carry the API key elsewhere, within a
# run or into the next one (the independent review, 9/29). Nothing in this repository needs to touch it.
BOB_CONFIG = re.compile(r"(?i)gateway_?url|BOB_GATEWAY|VITE_GATEWAY|\.bob/settings|trustedFolders|"
                        r"/etc/bob|policy\.json|BOB_WEB_LOGIN")


def inside(p):
    full = os.path.realpath(os.path.join(ROOT, os.path.expanduser(p)))
    return full == ROOT or full.startswith(ROOT + os.sep), os.path.relpath(full, ROOT)


def main():
    try:
        event = json.load(sys.stdin)
        tool = str(event.get("tool_name") or "")
        args = event.get("tool_input") or {}
    except Exception as e:  # noqa: BLE001 -- fail closed on unparseable input
        deny("?", f"tool guard could not parse its input ({type(e).__name__}); refusing")
    try:
        if DENY_TOOLS.search(tool):
            deny(tool, f"{tool} is disabled in this repository (no web, MCP or skill use)")
        if BOB_CONFIG.search(json.dumps([*strings(args, PATH_KEYS), args.get("command") or ""])):
            deny(tool, "refused: Bob's own configuration (its settings, policy or gateway) is off-limits "
                       "in this repository")
        if "command" in args and isinstance(args.get("command"), str):
            cmd = args["command"]
            for tok in (SHADOW_TOKEN.findall(cmd) if WRITES.search(cmd) else ()):
                if shadows_stdlib(tok):
                    deny(tool, f"command refused: {tok} would shadow a standard-library module")
            if DENY_COMMAND.search(cmd):
                deny(tool, "command refused: no network, remote, privileged, PBX, package-install or "
                           "git-writing "
                           "commands in this repository (tests, ruff and read-only git are fine)")
            if runs_live_code(cmd):
                deny(tool, "command refused: running the legacy code or the fax CLI would reach a PBX; "
                           "exercise it through pytest with mocked I/O")
            for tok in PATH_TOKEN.findall(cmd):
                t = tok.replace("$HOME", "~")
                if t.startswith(SYSTEM_OK) or t == "/":
                    if t == "/":
                        deny(tool, "command refused: it names the filesystem root")
                    continue
                if not inside(t)[0]:
                    deny(tool, "command refused: it names a path outside the repository "
                               "(use repo-relative paths)")
        is_write = bool(WRITE_TOOL.search(tool))
        for p in strings(args, PATH_KEYS):
            if not p.strip():
                continue
            ok, rel = inside(p)
            if not ok:
                deny(tool, "path refused: outside the repository")
            if is_write and shadows_stdlib(rel):
                deny(tool, f"write refused: {rel} would shadow a standard-library module "
                           "(the root, tests/ and scripts/ may not hold one)")
            if is_write and (rel.startswith(PROTECTED) or (rel + "/").startswith(PROTECTED)):
                deny(tool, f"write refused: {rel} is protected "
                           "(frozen baseline, git internals, or this guard)")
        if is_write:
            body = "\n".join(strings(args, CONTENT_KEYS))
            if body:
                r = subprocess.run([os.path.join(ROOT, "scripts", "scrub-check.sh"), "--stdin", "write",
                                    *REQUIRE], input=body.encode("utf-8"), capture_output=True, timeout=15,
                                   check=False)
                if r.returncode != 0:
                    deny(tool, "write refused: the content carries identifying data (masked): "
                               + r.stdout.decode("utf-8", "replace").strip().replace("\n", "; ")[:400])
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 -- fail closed: Bob treats a crashed hook as "allow"
        deny(tool, f"tool guard error ({type(e).__name__}); refusing")
    log("allow", tool, json.dumps(args)[:200])
    sys.exit(0)


if __name__ == "__main__":
    main()
