"""faxcli.cli — argparse entry point, thin I/O orchestration.

Subcommands: status, log, send, test.
All pure logic is in the other faxcli.* modules.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from typing import IO, Any

from faxcli import asterisk as ast_mod
from faxcli import cdr as cdr_mod
from faxcli.models import DryRunResult, LogResult, LogRow, StatusResult
from faxcli.numbers import InvalidNumber
from faxcli.transport import LocalTransport, Reading, SshTransport, Transport, exchange_host

TRUNK = "voipms-fax"
TEST_NUMBER = "19725329272"  # Faxbeep, public test receiver

# Default test page (legacy/fax/fax/cli.py:257 used docs/test-page.pdf; we use demo/)
_DEFAULT_TEST_PAGE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "demo", "test-page.pdf"
)


def _on_exchange() -> bool:
    # Compare the short hostname against the PBX host, which respects FAX_EXCHANGE_HOST
    # (legacy/fax/fax/cli.py:36).
    return socket.gethostname().split(".")[0] == exchange_host().split(".")[0]


def _make_transport(local: bool) -> Transport:
    if local or _on_exchange():
        return LocalTransport()
    return SshTransport()


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------

def cmd_status(a: argparse.Namespace, transport: Transport, stdout: IO[str]) -> int:
    readings: dict[str, Reading] = {}
    readings["fax show stats"] = transport.asterisk("fax show stats")
    readings["fax show sessions"] = transport.asterisk("fax show sessions")
    readings["pjsip show endpoint voipms-fax"] = transport.asterisk("pjsip show endpoint voipms-fax")
    readings["pjsip show registrations"] = transport.asterisk("pjsip show registrations")
    readings["pjsip show endpoint 2007"] = transport.asterisk("pjsip show endpoint 2007")
    readings["module show like res_fax"] = transport.asterisk("module show like res_fax")
    gs_reading = transport.which_gs()

    failed = [k for k, v in readings.items() if not v.ok]

    # Parse what we have (empty string for failed reads — safe defaults)
    stats = ast_mod.parse_stats(readings["fax show stats"].text)
    sessions = ast_mod.parse_sessions(readings["fax show sessions"].text)
    reg_registered = ast_mod.trunk_registered(readings["pjsip show registrations"].text)
    trunk_avail = ast_mod.contact_available(readings["pjsip show endpoint voipms-fax"].text, "voipms")
    obi_reg = ast_mod.contact_available(readings["pjsip show endpoint 2007"].text, "2007@")
    spandsp = ast_mod.module_loaded(readings["module show like res_fax"].text, "res_fax_spandsp")
    gs = bool(gs_reading.ok and gs_reading.text.strip())

    if failed:
        why = "could not read: " + ", ".join(failed)
        result = StatusResult(
            ok=False,
            spandsp=spandsp,
            trunk_registered=reg_registered,
            trunk_available=trunk_avail,
            obi100_registered=obi_reg,
            active_sessions=tuple(sessions),
            stats=stats,
            gs=gs,
            why=why,
            unread=tuple(failed),
        )
    else:
        result = StatusResult(
            ok=True,
            spandsp=spandsp,
            trunk_registered=reg_registered,
            trunk_available=trunk_avail,
            obi100_registered=obi_reg,
            active_sessions=tuple(sessions),
            stats=stats,
            gs=gs,
        )

    obj = result.to_json()
    if getattr(a, "json", False):
        print(json.dumps(obj), file=stdout)
    else:
        print(
            f"spandsp: {'loaded' if result.spandsp else 'MISSING'} · "
            f"trunk registered: {result.trunk_registered} · "
            f"trunk reachable: {result.trunk_available} · "
            f"OBi100 (MX922) registered: {result.obi100_registered} · "
            f"ghostscript: {result.gs}",
            file=stdout,
        )
        print(
            f"sent: {stats.get('Transmit Attempts', 0)} attempted, "
            f"{stats.get('Completed FAXes', 0)} completed, "
            f"{stats.get('Failed FAXes', 0)} failed (since Asterisk started) · "
            f"active now: {len(sessions)}",
            file=stdout,
        )
        if not result.ok:
            print(f"WARNING: {result.why}", file=stdout)
    return 0


# ---------------------------------------------------------------------------
# cmd_log
# ---------------------------------------------------------------------------

def cmd_log(a: argparse.Namespace, transport: Transport, stdout: IO[str]) -> int:
    tz = os.environ.get("FAX_TZ", "America/Los_Angeles")
    reading = transport.read_cdr(a.limit)
    if not reading.ok:
        obj: dict[str, Any] = {"ok": False, "why": reading.why, "rows": []}
        if getattr(a, "json", False):
            print(json.dumps(obj), file=stdout)
        else:
            print(f"error reading CDR: {reading.why}", file=stdout)
        return 1

    rows_raw = cdr_mod.parse_cdr(reading.text, a.limit)
    rows = cdr_mod.fax_rows(rows_raw, tz)

    if getattr(a, "json", False):
        log_rows = [LogRow.from_dict(r) for r in rows]
        result = LogResult(ok=True, rows=tuple(log_rows))
        print(json.dumps(result.to_json()), file=stdout)
    else:
        print(f"{'started (local)':16} {'dir':3} {'number':12} {'call':10} {'secs':>4}  file", file=stdout)
        for r in rows[: a.limit]:
            print(
                f"{r['start_local'][5:16]:16} {r['direction']:3} {r['number']:12} "
                f"{r['disposition']:10} {r['billsec']:>4}  {r['file']}",
                file=stdout,
            )
        print(
            "'call ANSWERED' means the line connected; whether pages went through is in "
            "`fax status` counters or --wait on send.",
            file=stdout,
        )
        if not rows:
            print("no fax calls in the CDR", file=stdout)
    return 0


# ---------------------------------------------------------------------------
# cmd_send
# ---------------------------------------------------------------------------

def cmd_send(a: argparse.Namespace, transport: Transport, stdout: IO[str]) -> int:
    """Thin printer over :func:`faxcli.api.send`.

    The printed JSON is identical to before (characterization tests prove it).
    """
    from faxcli.api import SendError, send  # noqa: PLC0415

    local = getattr(a, "local", False) or _on_exchange()
    try:
        result = send(
            a.pdf,
            a.number,
            label=a.label,
            dry_run=getattr(a, "dry_run", False),
            wait=getattr(a, "wait", 0),
            transport=transport,
            local=local,
        )
    except InvalidNumber as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except SendError as exc:
        print(f"error: {exc.reason}", file=sys.stderr)
        return 1

    if getattr(a, "json", False):
        print(json.dumps(result.to_json()), file=stdout)
    else:
        if isinstance(result, DryRunResult):
            print(
                f"dry run: {result.pages} page(s) spooled as {result.tif}; not dialed",
                file=stdout,
            )
        else:
            wait_val = getattr(a, "wait", 0)
            if wait_val and result.result is not None:
                r = result.result
                outcome = r.get("outcome", "?")
                disp = r.get("disposition", "?")
                secs = r.get("billsec", "?")
                wait_suffix = f"\nresult: {outcome} · call {disp} {secs}s"
            else:
                wait_suffix = "\nuse `fax log` to see the outcome"
            print(
                f"dialing {result.number} with {result.pages} page(s) → {result.tif}{wait_suffix}",
                file=stdout,
            )
    return 0


# ---------------------------------------------------------------------------
# cmd_inbound
# ---------------------------------------------------------------------------

def cmd_inbound(a: argparse.Namespace, _transport: Transport, stdout: IO[str]) -> int:
    """Print the generated dialplan and hook script to stdout; never writes a file."""
    from faxcli.inbound import InboundConfig, render_dialplan, render_hook  # noqa: PLC0415

    cfg = InboundConfig()
    print(render_dialplan(cfg), end="", file=stdout)
    print("", file=stdout)  # blank separator
    print(render_hook(cfg), end="", file=stdout)
    return 0


# ---------------------------------------------------------------------------
# cmd_test
# ---------------------------------------------------------------------------

def cmd_test(a: argparse.Namespace, transport: Transport, stdout: IO[str]) -> int:
    a.number = TEST_NUMBER
    a.label = "faxtest"
    if not getattr(a, "pdf", None):
        # Default test page: demo/test-page.pdf (legacy used docs/test-page.pdf)
        a.pdf = _DEFAULT_TEST_PAGE
    if not os.path.isfile(a.pdf):
        print(
            f"error: test page not found: {a.pdf}\n"
            "Place the test page at demo/test-page.pdf or pass --pdf explicitly.",
            file=sys.stderr,
        )
        return 1
    if not a.wait:
        a.wait = 90
    print("sending the test page to Faxbeep (public inbox: faxbeep.com)", file=stdout)
    return cmd_send(a, transport, stdout)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(
    argv: list[str] | None = None,
    transport: Transport | None = None,
    stdout: IO[str] | None = None,
) -> int:
    if stdout is None:
        stdout = sys.stdout

    p = argparse.ArgumentParser(prog="fax", description="send a PDF as a fax through the house PBX")
    p.add_argument("--local", action="store_true", help="run on this host (pbx) without ssh")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    s = p.add_subparsers(dest="cmd", required=True)

    q = s.add_parser("send", help="send a PDF")
    q.add_argument("pdf")
    q.add_argument("number")
    q.add_argument("--label")
    q.add_argument("--wait", type=int, default=0, metavar="SECS")
    q.add_argument("--dry-run", action="store_true")
    q.set_defaults(fn=cmd_send)

    q = s.add_parser("status", help="trunk, modules, counters")
    q.set_defaults(fn=cmd_status)

    q = s.add_parser("log", help="fax calls from the CDR")
    q.add_argument("--limit", type=int, default=20)
    q.set_defaults(fn=cmd_log)

    q = s.add_parser("test", help="send the test page to Faxbeep")
    q.add_argument("--pdf")
    q.add_argument("--wait", type=int, default=90)
    q.add_argument("--dry-run", action="store_true")
    q.set_defaults(fn=cmd_test, label=None)

    q = s.add_parser("inbound", help="print generated inbound-fax dialplan and hook script")
    q.add_argument("--render", action="store_true", help="print dialplan and hook (always on)")
    q.set_defaults(fn=cmd_inbound)

    a = p.parse_args(argv)

    if transport is None:
        transport = _make_transport(a.local)

    return a.fn(a, transport, stdout)


if __name__ == "__main__":
    sys.exit(main())
