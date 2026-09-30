"""faxconsole.export: the static replay demo, for GitHub Pages.

    python -m faxconsole.export FIXTURES > site.tar

This renders every GET route in replay mode, from the recorded and fictional fixtures, into files:
- api/<route>.json for each route. app.js reads these when the page says data-static="1".
- The page and its assets. index.html gets data-static="1", and a Content-Security-Policy meta tag,
  since Pages sends no headers.
- .nojekyll, so that Pages serves the files as they are.
The version drops the fields that only a running server has (started, uptime, runtime, os, host, pid),
as the realm-sigil static contract does. The VoIP.ms fixtures are synthesized, so their JSON carries no time.

It writes a tar stream to stdout. scripts/export-static.sh runs it inside the OS sandbox and extracts the
stream on the host, so the files never land in a directory Bob can write.
"""
from __future__ import annotations

import datetime
import io
import json
import os
import re
import sys
import tarfile
import zoneinfo
from typing import BinaryIO

from faxconsole.__main__ import build
from faxconsole.routes import _CSP, handle
from faxconsole.version import APP_DESC, APP_NAME, APP_REALM, APP_REPO, generate_name

# Every GET API route that handle() serves. A test holds this list to the dispatcher, so a new route cannot
# be left out of the static demo.
GET_API_ROUTES = ("/api/voipms", "/api/fax/status", "/api/fax/log", "/api/fax",
                  "/api/pbx/trunk", "/api/pbx/calls", "/api/pbx/endpoints", "/api/version")
PAGE_ASSETS = ("app.css", "app.js", "favicon.svg")
# What a commit's facts look like (scripts/export-static.sh reads them from git). Anything else is refused,
# so free text cannot reach the public version (the Oracle, on PR 20).
FACT_SHAPES = {"hash": re.compile(r"[0-9a-f]{7,40}"), "branch": re.compile(r"[A-Za-z0-9._/-]{1,64}"),
               "built": re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")}
# The VoIP.ms fixtures are synthesized, never captured (tests/fixtures/voipms/README.md). So the export
# carries no time for them: no fetched_at, and nothing computed from a clock, which a static copy would
# also freeze into a countdown (the Oracle, on PR 16).
VOIPMS_UNMEASURED = ("age", "stale", "days_to_billing", "polling", "fetched_at")


def sigil(facts: dict) -> dict:
    """The realm-sigil static contract: the fields its static/build.sh writes to version.json, in its order.
    One difference: "built" is the commit's own time, not the export's clock, so the export stays a pure
    function of the commit (two exports agree byte for byte)."""
    h = facts.get("hash", "dev")
    return {"name": APP_NAME, "description": APP_DESC, "version": generate_name(h, APP_REALM), "hash": h,
            "branch": facts.get("branch", "unknown"), "dirty": bool(facts.get("dirty", False)),
            "built": facts.get("built", "unknown"), "realm": APP_REALM, "repo": APP_REPO,
            "commit_url": f"{APP_REPO}/commit/{h}" if APP_REPO and h != "dev" else ""}


def sigil_meta(data: dict) -> str:
    """realm-sigil's <meta name="realm-version">: the JSON in a single-quoted attribute. &, ', < and > are
    escaped, which realm-sigil's build.sh does not do. A browser unescapes them, so a reader's JSON.parse
    is unchanged."""
    content = (json.dumps(data).replace("&", "&amp;").replace("'", "&#39;")
               .replace("<", "&lt;").replace(">", "&gt;"))       # a naive, non-HTML reader stays safe too
    return f"<meta name=\"realm-version\" content='{content}'>"


def api_file(route: str) -> str:
    """"/api/pbx/trunk" -> "api/pbx/trunk.json", the name that app.js's api() asks for."""
    return "api" + route[len("/api"):] + ".json"


def staticize(page: bytes, recorded: str, meta: str = "") -> bytes:
    """Mark the page static, with the time its data was recorded, and carry the CSP as a meta tag. A meta
    tag cannot carry frame-ancestors."""
    html = page.decode("utf-8")
    csp = "; ".join(d for d in _CSP.split("; ") if not d.startswith("frame-ancestors"))
    for old, new in (('<html lang="en">', f'<html lang="en" data-static="1" data-recorded="{recorded}">'),
                     ("<head>", f'<head>\n<meta http-equiv="Content-Security-Policy" content="{csp}">'),
                     ("</head>", (f"  {meta}\n" if meta else "") + "</head>"),
                     ("<h2>Live state</h2>", "<h2>Recorded state</h2>"),
                     # the live replay's banner promises a dry run, and a static copy cannot even do that
                     ("a send is a dry run and nothing is dialled",
                      "this static copy cannot send, so run it locally for a dry run; nothing is dialled")):
        if html.count(old) != 1:
            raise ValueError(f"export: the page must hold {old!r} exactly once")
        html = html.replace(old, new)
    return html.encode("utf-8")


def capture(fixtures: str) -> tuple[float, str]:
    """When the recorded PBX fixtures (asterisk/, cdr/) were captured, committed with them in
    capture.json, and its label, derived from it: one source of truth. The export dates the replay by it,
    never by its own clock, so the data are shown as old as they are and two exports agree byte for byte."""
    with open(os.path.join(fixtures, "capture.json"), encoding="utf-8") as f:
        meta = json.load(f)
    at = datetime.datetime.fromisoformat(meta["captured_at"])
    return at.timestamp(), at.astimezone(zoneinfo.ZoneInfo(meta["zone"])).strftime("%Y-%m-%d %H:%M %Z")


def export(fixtures: str, facts: dict | None = None) -> dict[str, bytes]:
    """Every file of the static demo, by its path in the site. *facts* are the commit's (hash, branch,
    built): scripts/export-static.sh reads them from git, since the sandbox cannot."""
    version = sigil(facts or {})
    captured, label = capture(fixtures)
    config, cleanup, _args = build(["--replay", fixtures], clock=lambda: captured)
    try:
        config.voipms._refresh_once()     # synchronously, rather than waiting for the poller's first round
        files: dict[str, bytes] = {}
        for route in GET_API_ROUTES:
            r = handle("GET", route, {}, b"", config)
            if r.status != 200:
                raise RuntimeError(f"export: GET {route} answered {r.status}")
            body = json.loads(r.body)
            if route == "/api/version":
                body = {**version, "replay": body.get("replay") is True}   # the static sigil, and the mode
            if route == "/api/voipms":
                body = {k: v for k, v in body.items() if k not in VOIPMS_UNMEASURED}
            files[api_file(route)] = (json.dumps(body, indent=1, sort_keys=True) + "\n").encode("utf-8")
        page = handle("GET", "/", {}, b"", config)
        # the chip shows "recorded <label>"; version.json is laid out as realm-sigil's build.sh writes it
        files["index.html"] = staticize(page.body, label, sigil_meta(version))
        files["version.json"] = (json.dumps(version, indent=2) + "\n").encode("utf-8")
        for name in PAGE_ASSETS:
            r = handle("GET", "/" + name, {}, b"", config)
            if r.status != 200:
                raise RuntimeError(f"export: GET /{name} answered {r.status}")
            files[name] = r.body
        files[".nojekyll"] = b""
        return files
    finally:
        cleanup()


def write_tar(files: dict[str, bytes], out: BinaryIO) -> None:
    """Regular files only, in name order, with fixed metadata: the same files give the same bytes, and two
    exports of one commit give the same files."""
    with tarfile.open(fileobj=out, mode="w|", format=tarfile.PAX_FORMAT) as tar:
        for name in sorted(files):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(files[name]), 0o644, 0
            tar.addfile(info, io.BytesIO(files[name]))


def _prefix_outside(tree: str) -> bool:
    """True when Python's bytecode cache is set and the place it mirrors tree to lies outside tree.

    Python caches <tree>/x.py at <prefix>/<tree>/x.pyc, so the mirrored path is what must be outside, not the
    prefix itself: a prefix of "/" is outside no tree but mirrors every tree onto itself (the Oracle, on #32).
    """
    if not sys.pycache_prefix:
        return False
    root = os.path.realpath(tree)
    mirror = os.path.realpath(os.path.join(os.path.realpath(sys.pycache_prefix), root.lstrip(os.sep)))
    return os.path.commonpath([mirror, root]) != root


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) not in (1, 4):
        print("usage: python -m faxconsole.export FIXTURES [HASH BRANCH BUILT] > site.tar", file=sys.stderr)
        return 2
    facts = dict(zip(("hash", "branch", "built"), args[1:], strict=True)) if len(args) == 4 else None
    if facts and not all(FACT_SHAPES[k].fullmatch(v) for k, v in facts.items()):
        print(f"export: refusing facts that are not a commit's: {facts}", file=sys.stderr)
        return 2
    if facts and not _prefix_outside(os.getcwd()):
        # With facts this is the publish path (scripts/export-in-sandbox.sh). Python must read its bytecode
        # from a cache outside the exported tree. This is a misconfiguration tripwire: by the time main()
        # runs, the imports are done, so a planted .pyc would already have run (the Oracle, on #32). The
        # enforcement is -X pycache_prefix on the sandboxed exec line and export-static.sh refusing a
        # tracked __pycache__ or .pyc.
        print(f"export: refusing to publish: sys.pycache_prefix is {sys.pycache_prefix!r}, "
              "not a directory outside the exported tree (set PYTHONPYCACHEPREFIX)", file=sys.stderr)
        return 2
    write_tar(export(args[0], facts), sys.stdout.buffer)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
