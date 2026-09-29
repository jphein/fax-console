"""faxconsole.routes — pure request handler.

``handle(method, path, headers, body, transport, config)`` is a pure
function: it receives a request and returns a Response.  No sockets, no
globals.  The http.server adapter in server.py calls it.

Routes implemented:
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
from typing import Any
from urllib.parse import parse_qs, urlparse

from faxcli import cli as cli_mod
from faxcli.api import SendError
from faxcli.api import send as api_send
from faxcli.numbers import InvalidNumber
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

@dataclass
class Response:
    """An HTTP response ready to be serialised."""

    status: int
    body: bytes
    content_type: str = "application/json"


def _json_response(status: int, obj: Any) -> Response:
    return Response(status=status, body=json.dumps(obj).encode())


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
    return _ok(config.voipms.snapshot())


def _route_status(config: Config) -> Response:
    """GET /api/fax/status — faxcli cmd_status result as JSON."""
    a = argparse.Namespace(json=True)
    buf = io.StringIO()
    cli_mod.cmd_status(a, config.transport, buf)
    text = buf.getvalue().strip()
    try:
        obj = json.loads(text.splitlines()[-1])
    except Exception as e:
        return _err(500, {"ok": False, "why": f"unparseable status output: {e}"})
    return _ok(obj)


def _route_log(path: str, config: Config) -> Response:
    """GET /api/fax/log?limit=N — faxcli cmd_log result as JSON."""
    qs = parse_qs(urlparse(path).query)
    try:
        limit = int(qs.get("limit", ["20"])[0])
    except (ValueError, IndexError):
        limit = 20
    a = argparse.Namespace(json=True, limit=limit)
    buf = io.StringIO()
    cli_mod.cmd_log(a, config.transport, buf)
    text = buf.getvalue().strip()
    try:
        obj = json.loads(text.splitlines()[-1])
    except Exception as e:
        return _err(500, {"ok": False, "why": f"unparseable log output: {e}"})
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
        st = {"ok": False, "why": f"unparseable status: {e}"}

    # Get log (25 rows, matching legacy fax_state e:2032)
    a_lg = argparse.Namespace(json=True, limit=25)
    buf_lg = io.StringIO()
    cli_mod.cmd_log(a_lg, config.transport, buf_lg)
    try:
        lg: dict = json.loads(buf_lg.getvalue().strip().splitlines()[-1])
    except Exception as e:
        lg = {"ok": False, "why": f"unparseable log: {e}", "rows": []}

    result = {
        "ok": bool(st.get("ok")) and bool(lg.get("ok")),
        "status": st,
        "log": lg.get("rows", []),
        "why": st.get("why") or lg.get("why"),
        "src": "faxcli --local --json status | log --limit 25",
        "spool": config.spool,
        "inbox": config.inbox,
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
    from faxcli.numbers import normalize  # noqa: PLC0415

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
        return {"ok": False, "detail": f"could not store the PDF: {e}"}

    # Call faxcli.api.send directly (no argparse, no JSON round-trip)
    try:
        result = api_send(
            path,
            number,
            label=label,
            dry_run=config.replay,   # replay → always dry run
            wait=0,
            transport=config.transport,
            local=True,              # console always spool-local
        )
    except InvalidNumber as exc:
        return {"ok": False, "detail": str(exc)}
    except SendError as exc:
        return {"ok": False, "detail": exc.reason}

    r = result.to_json()
    r["ok"] = True
    r["pdf"] = path
    if config.replay:
        r["replay"] = True
        r["detail"] = "replay: nothing is dialled"
    else:
        r["detail"] = (
            f"dialing {number} with {r.get('pages', '?')} page(s); the outcome appears in "
            "the log below when the call ends (judged by the fax counters, not the call disposition)"
        )
    return r


def _route_version() -> Response:
    """GET /api/version — realm-sigil contract."""
    return _ok(version_dict())


def _route_not_found(path: str) -> Response:
    """404 with HTML-escaped path (legacy e:2907–2911)."""
    escaped = _html_escape(path)
    body = json.dumps({
        "ok": False,
        "status": 404,
        "detail": f"No such route: {escaped}",
    })
    return Response(status=404, body=body.encode())


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
            return _route_version()

    if method == "POST" and route == "/api/fax/send":
        return _route_send(headers, body, config)

    return _route_not_found(path)
