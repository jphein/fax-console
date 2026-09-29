"""faxconsole.export: the static replay demo, for GitHub Pages.

    python -m faxconsole.export FIXTURES > site.tar

This renders every GET route in replay mode, from the recorded and fictional fixtures, into files:
- api/<route>.json for each route. app.js reads these when the page says data-static="1".
- The page and its assets. index.html gets data-static="1", and a Content-Security-Policy meta tag,
  since Pages sends no headers.
- .nojekyll, so that Pages serves the files as they are.
The version drops the fields that only a running server has (started, uptime, runtime, os, host, pid),
as the realm-sigil static contract does, and the VoIP.ms fetched_at is given in UTC, not the host's zone.

It writes a tar stream to stdout. scripts/export-static.sh runs it inside the OS sandbox and extracts the
stream on the host, so the files never land in a directory Bob can write.
"""
from __future__ import annotations

import datetime
import io
import json
import sys
import tarfile
from typing import BinaryIO

from faxconsole.__main__ import build
from faxconsole.routes import _CSP, handle

# Every GET API route that handle() serves. A test holds this list to the dispatcher, so a new route cannot
# be left out of the static demo.
GET_API_ROUTES = ("/api/voipms", "/api/fax/status", "/api/fax/log", "/api/fax",
                  "/api/pbx/trunk", "/api/pbx/calls", "/api/pbx/endpoints", "/api/version")
PAGE_ASSETS = ("app.css", "app.js", "favicon.svg")
# realm-sigil: "Static sites omit server-only fields".
SERVER_ONLY = ("started", "uptime", "runtime", "os", "host", "pid")
# VoIP.ms fields computed from the export's own clock: a static copy would freeze them into a countdown.
# The page's static mode reads fetched_at and did_next_billing instead.
VOIPMS_FROZEN = ("age", "stale", "days_to_billing", "polling")


def utc(local: str) -> str:
    """The poller writes fetched_at in the host's local time. A static site would freeze that zone onto a
    public page, so the export gives the same instant in UTC."""
    t = datetime.datetime.strptime(local, "%Y-%m-%d %H:%M:%S").astimezone(datetime.timezone.utc)
    return t.strftime("%Y-%m-%d %H:%M:%S UTC")


def api_file(route: str) -> str:
    """"/api/pbx/trunk" -> "api/pbx/trunk.json", the name that app.js's api() asks for."""
    return "api" + route[len("/api"):] + ".json"


def staticize(page: bytes, exported: str) -> bytes:
    """Mark the page static, with the time it was exported, and carry the CSP as a meta tag. A meta tag
    cannot carry frame-ancestors."""
    html = page.decode("utf-8")
    csp = "; ".join(d for d in _CSP.split("; ") if not d.startswith("frame-ancestors"))
    for old, new in (('<html lang="en">', f'<html lang="en" data-static="1" data-exported="{exported}">'),
                     ("<head>", f'<head>\n<meta http-equiv="Content-Security-Policy" content="{csp}">'),
                     ("<h2>Live state</h2>", "<h2>Recorded state</h2>"),
                     # the live replay's banner promises a dry run, and a static copy cannot even do that
                     ("a send is a dry run and nothing is dialled",
                      "this static copy cannot send, so run it locally for a dry run; nothing is dialled")):
        if html.count(old) != 1:
            raise ValueError(f"export: the page must hold {old!r} exactly once")
        html = html.replace(old, new)
    return html.encode("utf-8")


def export(fixtures: str) -> dict[str, bytes]:
    """Every file of the static demo, by its path in the site."""
    config, cleanup, _args = build(["--replay", fixtures])
    try:
        config.voipms._refresh_once()     # synchronously, rather than waiting for the poller's first round
        files: dict[str, bytes] = {}
        for route in GET_API_ROUTES:
            r = handle("GET", route, {}, b"", config)
            if r.status != 200:
                raise RuntimeError(f"export: GET {route} answered {r.status}")
            body = json.loads(r.body)
            if route == "/api/version":
                body = {k: v for k, v in body.items() if k not in SERVER_ONLY}
            if route == "/api/voipms":
                body = {k: v for k, v in body.items() if k not in VOIPMS_FROZEN}
                if body.get("fetched_at"):
                    body["fetched_at"] = utc(body["fetched_at"])
            files[api_file(route)] = (json.dumps(body, indent=1, sort_keys=True) + "\n").encode("utf-8")
        page = handle("GET", "/", {}, b"", config)
        # One time for the whole snapshot, shown by the page's freshness chip instead of "live". It is the
        # export's time: the fixtures themselves were recorded earlier.
        exported = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        files["index.html"] = staticize(page.body, exported)
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
    """Regular files only, in name order, with fixed metadata: the same files give the same bytes. (An
    export stamps the time it ran on the page, so two exports differ there.)"""
    with tarfile.open(fileobj=out, mode="w|", format=tarfile.PAX_FORMAT) as tar:
        for name in sorted(files):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(files[name]), 0o644, 0
            tar.addfile(info, io.BytesIO(files[name]))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m faxconsole.export FIXTURES > site.tar", file=sys.stderr)
        return 2
    write_tar(export(args[0]), sys.stdout.buffer)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
