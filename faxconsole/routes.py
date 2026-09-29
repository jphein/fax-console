"""faxconsole.routes — pure request handler.

``handle(method, path, headers, body, transport, config)`` is a pure
function: it receives a request and returns a Response.  No sockets, no
globals.  The http.server adapter in server.py calls it.

Routes implemented:
  GET  /                     — index.html (faxconsole page)
  GET  /app.css              — stylesheet
  GET  /app.js               — JavaScript
  GET  /favicon.svg          — favicon
  GET  /api/fax/status       — faxcli status JSON
  GET  /api/fax/log?limit=N  — faxcli log JSON
  GET  /api/fax              — legacy combined shape (fax_state)
  GET  /api/pbx/trunk        — read_trunk dict
  GET  /api/pbx/calls        — read_calls dict
  GET  /api/pbx/endpoints    — read_sip_endpoints dict
  POST /api/fax/send         — multipart PDF upload
  GET  /api/version          — realm-sigil contract
  *    anything else          — 404 with escaped path

Write gate: X-Auth-Token header checked with hmac.compare_digest (legacy
write_authorized, e:2914–2951).  Fails closed when no token is configured.
"""
from __future__ import annotations

import argparse
import datetime
import hmac
import io
import json
import os
import re
from dataclasses import dataclass
from importlib.resources import files as _pkg_files
from typing import Any
from urllib.parse import parse_qs, urlparse

from faxcli import cli as cli_mod
from faxcli.api import SendError
from faxcli.api import send as api_send
from faxcli.phone_numbers import InvalidNumber
from faxcli.transport import Transport
from faxconsole.pbx import read_calls, read_sip_endpoints, read_trunk
from faxconsole.version import version_dict

# ---------------------------------------------------------------------------
# Constants (portable defaults; __main__ can inject a Config)
# ---------------------------------------------------------------------------

FAX_MAX_BYTES = 15 * 1024 * 1024  # 15 MB, matching legacy e:2007


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Content-Security-Policy applied to every page response
# ---------------------------------------------------------------------------

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)

_STATIC_DIR = _pkg_files("faxconsole").joinpath("static")

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".svg":  "image/svg+xml",
}


@dataclass
class Response:
    """An HTTP response ready to be serialised."""

    status: int
    body: bytes
    content_type: str = "application/json"
    extra_headers: dict[str, str] | None = None


def _json_response(status: int, obj: Any) -> Response:
    return Response(
        status=status,
        body=json.dumps(obj).encode(),
        extra_headers={"X-Content-Type-Options": "nosniff"},
    )


def _ok(obj: Any) -> Response:
    return _json_response(200, obj)


def _bad(obj: Any) -> Response:
    return _json_response(400, obj)


def _err(code: int, obj: Any) -> Response:
    return _json_response(code, obj)


# ---------------------------------------------------------------------------
# HTML escaper (port of legacy html_escape e:2656–2702)
# ---------------------------------------------------------------------------

def _html_escape(t: str) -> str:
    return (
        str(t)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


# ---------------------------------------------------------------------------
# Multipart parser (port of legacy _multipart e:2040–2055)
# ---------------------------------------------------------------------------

def _multipart(content_type: str, body: bytes) -> tuple[dict, dict]:
    """(fields, files) from a multipart/form-data body."""
    from email.parser import BytesParser  # noqa: PLC0415
    from email.policy import default  # noqa: PLC0415

    msg = BytesParser(policy=default).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    )
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition") or ""
        fn = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if fn:
            files[name] = (fn, payload)
        else:
            fields[name] = payload.decode("utf-8", "replace").strip()
    return fields, files


# ---------------------------------------------------------------------------
# Write-token gate (port of legacy write_authorized e:2914–2951)
# ---------------------------------------------------------------------------

def _write_token(config: Config) -> str:
    """Expected token: from Config, then env (like legacy write_token e:2651–2653)."""
    tok = config.write_token if config.write_token is not None else ""
    if not tok:
        tok = os.environ.get("TELEPHONY_CONSOLE_TOKEN", "")
    return tok.strip()


def _write_authorized(headers: dict[str, str], config: Config) -> Response | None:
    """Return a 401 Response if the write token check fails, else None.

    Fails closed when no token is configured (legacy e:2928–2938).
    """
    expected = _write_token(config)
    supplied = (headers.get("x-auth-token") or "").strip()
    if not expected:
        return _err(401, {
            "ok": False,
            "detail": (
                "write refused: this server has no write token configured. "
                "Set TELEPHONY_CONSOLE_TOKEN in the environment."
            ),
        })
    if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        return _err(401, {"ok": False, "detail": "write refused: missing or incorrect X-Auth-Token."})
    return None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class Config:
    """Runtime configuration injected into handle()."""

    transport: Transport
    inbox: str = "/var/lib/faxconsole/fax"
    spool: str = "/var/spool/asterisk/fax"
    max_bytes: int = FAX_MAX_BYTES
    write_token: str | None = None   # if None, falls back to env
    replay: bool = False             # replay mode: POST /api/fax/send → dry run
    voipms: Any = None               # VoipMsPoller instance, or None
    replay_root: str | None = None   # replay mode: the temp dir that runtime paths are shown relative to
    replay_fixture_dir: str | None = None   # replay mode: the --replay DIR, masked exactly in error text

    def __post_init__(self) -> None:
        from faxcli.transport import ReplayTransport  # noqa: PLC0415
        if self.replay and not isinstance(self.transport, ReplayTransport):
            raise TypeError(
                "Config(replay=True) requires a ReplayTransport; "
                f"got {type(self.transport).__name__!r}"
            )


# ---------------------------------------------------------------------------
# Route implementations
# ---------------------------------------------------------------------------

def _route_voipms(config: Config) -> Response:
    """GET /api/voipms — VoIP.ms poller snapshot (legacy e:2859–2861)."""
    if config.voipms is None:
        return _err(503, {"ok": False, "detail": "VoIP.ms poller not configured"})
    snap = config.voipms.snapshot()
    if config.replay and snap.get("error"):
        snap = dict(snap)
        snap["error"] = _mask_error(config, snap["error"])
    return _ok(snap)


def _route_status(config: Config) -> Response:
    """GET /api/fax/status — faxcli cmd_status result as JSON."""
    a = argparse.Namespace(json=True)
    buf = io.StringIO()
    cli_mod.cmd_status(a, config.transport, buf)
    text = buf.getvalue().strip()
    try:
        obj = json.loads(text.splitlines()[-1])
    except Exception as e:
        why = _mask_error(config, f"unparseable status output: {e}")
        return _err(500, {"ok": False, "why": why})
    if config.replay and obj.get("why"):
        obj = dict(obj)
        obj["why"] = _mask_error(config, obj["why"])
    return _ok(obj)


def _route_log(path: str, config: Config) -> Response:
    """GET /api/fax/log?limit=N — faxcli cmd_log result as JSON."""
    qs = parse_qs(urlparse(path).query)
    try:
        limit = int(qs.get("limit", ["20"])[0])
    except (ValueError, IndexError):
        limit = 20
    limit = max(1, min(limit, 1000))  # clamp: 1..1000 (item 3)
    a = argparse.Namespace(json=True, limit=limit)
    buf = io.StringIO()
    cli_mod.cmd_log(a, config.transport, buf)
    text = buf.getvalue().strip()
    try:
        obj = json.loads(text.splitlines()[-1])
    except Exception as e:
        why = _mask_error(config, f"unparseable log output: {e}")
        return _err(500, {"ok": False, "why": why})
    if config.replay and obj.get("why"):
        obj = dict(obj)
        obj["why"] = _mask_error(config, obj["why"])
    return _ok(obj)


def _route_fax_state(config: Config) -> Response:
    """GET /api/fax — legacy combined shape (fax_state e:2030–2037)."""
    # Get status
    a_st = argparse.Namespace(json=True)
    buf_st = io.StringIO()
    cli_mod.cmd_status(a_st, config.transport, buf_st)
    try:
        st: dict = json.loads(buf_st.getvalue().strip().splitlines()[-1])
    except Exception as e:
        st = {"ok": False, "why": _mask_error(config, f"unparseable status: {e}")}

    # Get log (25 rows, matching legacy fax_state e:2032)
    a_lg = argparse.Namespace(json=True, limit=25)
    buf_lg = io.StringIO()
    cli_mod.cmd_log(a_lg, config.transport, buf_lg)
    try:
        lg: dict = json.loads(buf_lg.getvalue().strip().splitlines()[-1])
    except Exception as e:
        lg = {"ok": False, "why": _mask_error(config, f"unparseable log: {e}"), "rows": []}

    # Mask why fields from the CLI's own error output (e.g. CDR read failure with a path)
    if config.replay:
        if st.get("why"):
            st = dict(st)
            st["why"] = _mask_error(config, st["why"])
        if lg.get("why"):
            lg = dict(lg)
            lg["why"] = _mask_error(config, lg["why"])

    spool = "replay:spool" if config.replay else config.spool
    inbox = "replay:inbox" if config.replay else config.inbox
    combined_why = st.get("why") or lg.get("why")
    result = {
        "ok": bool(st.get("ok")) and bool(lg.get("ok")),
        "status": st,
        "log": lg.get("rows", []),
        "why": combined_why,
        "src": "faxcli --local --json status | log --limit 25",
        "spool": spool,
        "inbox": inbox,
    }
    return _ok(result)


def _route_pbx_trunk(config: Config) -> Response:
    """GET /api/pbx/trunk."""
    return _ok(read_trunk(config.transport))


def _route_pbx_calls(config: Config) -> Response:
    """GET /api/pbx/calls."""
    return _ok(read_calls(config.transport))


def _route_pbx_endpoints(config: Config) -> Response:
    """GET /api/pbx/endpoints."""
    return _ok(read_sip_endpoints(config.transport))


def _route_send(headers: dict[str, str], body: bytes, config: Config) -> Response:
    """POST /api/fax/send — port of legacy do_POST /api/fax/send (e:2958–2974)."""
    # Write gate
    auth_err = _write_authorized(headers, config)
    if auth_err is not None:
        return auth_err

    # Size cap (legacy e:2960–2961: Content-Length > FAX_MAX_BYTES + 65536)
    try:
        content_length = int(headers.get("content-length") or len(body))
    except (ValueError, TypeError):
        content_length = len(body)
    if content_length > config.max_bytes + 65536:
        return _err(413, {"ok": False, "detail": "upload too large (15 MB max)"})

    ctype = headers.get("content-type", "")
    if not ctype.startswith("multipart/form-data"):
        return _bad({"ok": False, "detail": "expected multipart/form-data"})

    try:
        fields, files = _multipart(ctype, body)
    except Exception as e:
        return _bad({"ok": False, "detail": f"bad body: {e}"})

    if fields.get("confirm") != "yes":
        return _bad({
            "ok": False,
            "detail": (
                "refused: this dials a real number and delivers a document, "
                "so it requires an explicit confirmation"
            ),
        })

    result = _fax_send(fields, files, config)
    return _json_response(200 if result.get("ok") else 400, result)


def _fax_send(fields: dict, files: dict, config: Config) -> dict[str, Any]:
    """Port of legacy fax_send (e:2058–2090), calling faxcli.api.send directly."""
    from faxcli.phone_numbers import normalize  # noqa: PLC0415

    # Validate number (legacy e:2060–2066)
    raw_number = fields.get("number", "")
    try:
        number = normalize(raw_number)
    except InvalidNumber as exc:
        return {"ok": False, "detail": str(exc)}

    # Must have a file
    if "file" not in files:
        return {"ok": False, "detail": "no PDF attached"}
    fn, data = files["file"]

    # PDF check (legacy e:2070–2071)
    if not data.startswith(b"%PDF-"):
        return {"ok": False, "detail": "only PDF files are accepted"}

    # Size cap (legacy e:2072–2073)
    if len(data) > config.max_bytes:
        return {"ok": False, "detail": "PDF larger than 15 MB"}

    # Build label (legacy e:2074)
    raw_label = fields.get("label") or os.path.splitext(fn)[0]
    label = re.sub(r"[^A-Za-z0-9_-]+", "-", raw_label)[:40] or "fax"

    # Write PDF to inbox (legacy e:2075–2082)
    try:
        os.makedirs(config.inbox, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")  # noqa: DTZ005
        path = os.path.join(config.inbox, f"{stamp}-{label}.pdf")
        with open(path, "wb") as fh:
            fh.write(data)
    except OSError as e:
        return {"ok": False, "detail": _mask_error(config, f"could not store the PDF: {e}")}

    # Call faxcli.api.send directly (no argparse, no JSON round-trip)
    from faxcli.transport import LocalTransport as _LocalTransport  # noqa: PLC0415
    try:
        result = api_send(
            path,
            number,
            label=label,
            dry_run=config.replay,   # replay → always dry run
            wait=0,
            transport=config.transport,
            local=isinstance(config.transport, _LocalTransport),  # item 3: local only for LocalTransport
        )
    except InvalidNumber as exc:
        return {"ok": False, "detail": str(exc)}
    except SendError as exc:
        return {"ok": False, "detail": _mask_error(config, exc.reason)}

    r = result.to_json()
    r["ok"] = True
    r["pdf"] = path
    if config.replay:
        r["replay"] = True
        r["detail"] = "replay: nothing is dialled"
        # The public demo never names the machine's directories (review of run 11): see _public_path.
        for _k in ("pdf", "tif"):
            if isinstance(r.get(_k), str):
                r[_k] = _public_path(config, r[_k])
    else:
        r["detail"] = (
            f"dialing {number} with {r.get('pages', '?')} page(s); the outcome appears in "
            "the log below when the call ends (judged by the fax counters, not the call disposition)"
        )
    return r


def _public_path(config: Config, path: str) -> str:
    """How a runtime path is shown. In replay mode, the public demo, a path under the replay root reads
    "replay:/…" relative to it, and any other absolute path reads "replay:<name>". The machine's directories
    never appear. Live mode, which only the LAN sees, shows paths as they are.

    Review of run 11: the first version stripped os.path.commonpath([inbox, spool]). When those share only
    "/", that strips a single slash, and "replay:tmp/…" still named the whole temp dir.
    """
    if not config.replay:
        return path
    root = (config.replay_root or "").rstrip(os.sep)
    if root and (path == root or path.startswith(root + os.sep)):
        return "replay:" + (path[len(root):] or "/")
    if os.path.isabs(path):
        return "replay:" + os.path.basename(path)
    return path


# What replay says instead of an error that names a path it does not know.
REPLAY_ERROR_WITHHELD = "error details withheld in replay mode"
# A known dir ends where its path does: at a "/", a quote, whitespace or the end ("/opt/fx-2" is not
# "/opt/fx").
_KNOWN_DIR_END = r"(?=[/'\"\s]|$)"
# What a replacement leaves: "replay:", and the path inside the known dir.
_REPLAY_TOKEN = re.compile(r"replay:(?:/[^\s'\"]*)?")


def _mask_error(config: Config, text: str) -> str:
    """In replay mode, take every machine path out of *text*, an error message. Live mode, which only
    the LAN sees, returns it unchanged.

    The directories replay knows, the replay root (the temp dir) and the fixture dir, are replaced
    EXACTLY by "replay:", at a path boundary. Each is replaced in two forms: as str() gives it, and as
    repr() escapes it, since OSError and KeyError quote a file name with repr(). An exact replacement
    survives a space or a quote inside the name. After that the mask fails closed. If any "/" is left
    outside the replay: tokens, the error named some other path or a URL, and the whole message becomes
    REPLAY_ERROR_WITHHELD: no legitimate replay error names any other path.

    - Review of PR 8, S-a: the first version masked token by token. A token ends at a space or a
      quote, so a deploy path such as "/srv/x y/fixtures" left " y/fixtures" behind.
    - The Oracle's delta on PR 11: a replacement without a boundary turned "/opt/fx-zqx7" into
      "replay:-zqx7"; a repr()-escaped name escaped the exact replacement; and a token fallback kept
      paths glued to other text ("path:/srv/x"). Failing closed covers all three.
    - It keys on "/", so text with no slash passes as it is: a host name, an address, a user name. No
      replay code path emits such text: ReplayTransport and fixture_http do no network or user lookups,
      and no user input reaches a masked field. So that gap is latent (the Oracle, on PR 15).
    """
    if not config.replay:
        return text
    known = {d.rstrip(os.sep) for d in (config.replay_root, config.replay_fixture_dir) if d}
    forms = {f for d in known if d for f in (d, repr(d)[1:-1])}
    for f in sorted(forms, key=len, reverse=True):
        text = re.sub(re.escape(f) + _KNOWN_DIR_END, "replay:", text)
    if "/" in _REPLAY_TOKEN.sub("", text):
        return REPLAY_ERROR_WITHHELD
    return text


def _route_version(config: Config | None = None) -> Response:
    """GET /api/version — realm-sigil contract."""
    d = version_dict()
    if config is not None:
        d["replay"] = config.replay
        if config.replay:
            # Replay mode is the public demo. The sigil's `host` is the machine's own name,
            # which on a house host is exactly what the scrub gate keeps out of public view.
            d["host"] = "replay"
    return _ok(d)


def _route_static(filename: str) -> Response:
    """Serve a static file from faxconsole/static/ with CSP headers."""
    ext = os.path.splitext(filename)[1]
    content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")
    try:
        data = _STATIC_DIR.joinpath(filename).read_bytes()
    except (FileNotFoundError, OSError):
        return _route_not_found(f"/{filename}")
    return Response(
        status=200,
        body=data,
        content_type=content_type,
        extra_headers={
            "Content-Security-Policy": _CSP,
            "X-Content-Type-Options": "nosniff",  # already present; _json_response adds it for APIs
        },
    )


def _route_not_found(path: str) -> Response:
    """404 with HTML-escaped path (legacy e:2907–2911)."""
    escaped = _html_escape(path)
    body = json.dumps({
        "ok": False,
        "status": 404,
        "detail": f"No such route: {escaped}",
    })
    return Response(
        status=404,
        body=body.encode(),
        extra_headers={
            "Content-Security-Policy": _CSP,
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

def handle(
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes,
    config: Config,
) -> Response:
    """Pure request dispatcher.  No sockets, no globals.

    ``headers`` keys are lowercased by the caller (server.py normalises them).
    """
    # Normalise method to upper case
    method = method.upper()

    # Strip query string for route matching
    parsed = urlparse(path)
    route = parsed.path

    if method == "GET":
        if route in ("/", "/index.html"):
            return _route_static("index.html")
        if route == "/app.css":
            return _route_static("app.css")
        if route == "/app.js":
            return _route_static("app.js")
        if route == "/favicon.svg":
            return _route_static("favicon.svg")
        if route == "/api/voipms":
            return _route_voipms(config)
        if route == "/api/fax/status":
            return _route_status(config)
        if route == "/api/fax/log":
            return _route_log(path, config)
        if route == "/api/fax":
            return _route_fax_state(config)
        if route == "/api/pbx/trunk":
            return _route_pbx_trunk(config)
        if route == "/api/pbx/calls":
            return _route_pbx_calls(config)
        if route == "/api/pbx/endpoints":
            return _route_pbx_endpoints(config)
        if route == "/api/version":
            return _route_version(config)

    if method == "POST" and route == "/api/fax/send":
        return _route_send(headers, body, config)

    return _route_not_found(path)
