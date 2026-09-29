"""faxcli.api — typed send API.

``send(pdf, number, *, label=None, dry_run=False, wait=0, transport)``
returns a :class:`~faxcli.models.DryRunResult` or
:class:`~faxcli.models.SendResult`, or raises :class:`InvalidNumber` /
:class:`SendError`.

``faxconsole`` calls this directly instead of parsing JSON printed by
``cmd_send``.  The printed JSON contract is unchanged: ``cmd_send`` is now a
thin printer over this function.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import tempfile

from faxcli import asterisk as ast_mod
from faxcli import cdr as cdr_mod
from faxcli import outcome as outcome_mod
from faxcli.models import DryRunResult, SendResult
from faxcli.phone_numbers import normalize
from faxcli.transport import Transport

TRUNK = cdr_mod.TRUNK   # one definition, in faxcli.cdr, the lowest module that needs it
SPOOL = "/var/spool/asterisk/fax"

__all__ = ["SendError", "send"]


class SendError(Exception):
    """Raised when a send attempt fails for a non-number reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def send(
    pdf: str,
    number: str,
    *,
    label: str | None = None,
    dry_run: bool = False,
    wait: int = 0,
    transport: Transport,
    local: bool = False,
) -> DryRunResult | SendResult:
    """Convert *pdf* to a TIFF and queue (or dry-run) a fax to *number*.

    Args:
        pdf:       path to the PDF file.
        number:    raw destination number (normalised internally).
        label:     optional label; defaults to the PDF basename (sans extension).
        dry_run:   if True, render and spool the TIFF but never originate.
        wait:      seconds to wait for a result (0 = fire-and-forget).
        transport: the I/O seam; injected by callers and tests.
        local:     whether the caller is running on the PBX host.

    Returns:
        :class:`~faxcli.models.DryRunResult` when *dry_run* is True, else
        :class:`~faxcli.models.SendResult`.

    Raises:
        :class:`~faxcli.numbers.InvalidNumber`: if *number* cannot be normalised.
        :class:`SendError`: for any other failure (file missing, render error, …).
    """
    # Normalise number (raises InvalidNumber on failure — callers catch it)
    number = normalize(number)

    # File existence
    if not os.path.isfile(pdf):
        raise SendError(f"no such file: {pdf}")

    # PDF header check
    if pdf.lower().endswith(".pdf"):
        with open(pdf, "rb") as f:
            if f.read(5) != b"%PDF-":
                raise SendError("not a PDF")

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")  # noqa: DTZ005
    resolved_label = re.sub(
        r"[^A-Za-z0-9_-]+", "-",
        label or os.path.splitext(os.path.basename(pdf))[0],
    )[:40]
    name = f"{stamp}-{resolved_label}-{number}.tif"

    from faxcli.tiff import count_pages_from_path  # noqa: PLC0415

    if local:
        localtif = os.path.join(SPOOL, name)
        _tmpdir = None
    else:
        _tmpdir = tempfile.mkdtemp()
        localtif = os.path.join(_tmpdir, name)
    spooled = os.path.join(SPOOL, name)

    # The temp dir is removed on every path, a failed render and an unreadable TIFF included
    # (review of run 12: a failed render raised before any cleanup and left the directory behind).
    try:
        render_reading = transport.render(pdf, localtif)
        if not render_reading.ok:
            raise SendError(f"render failed: {render_reading.why}")
        actual_localtif = render_reading.text

        pages = count_pages_from_path(actual_localtif)

        spool_reading = transport.spool(actual_localtif, name, spooled)
        if not spool_reading.ok:
            raise SendError(f"spool failed: {spool_reading.why}")
        effective_tif = spool_reading.text if spool_reading.text else spooled

        transport.cleanup(actual_localtif)
    finally:
        if _tmpdir:
            import shutil  # noqa: PLC0415
            shutil.rmtree(_tmpdir, ignore_errors=True)

    if dry_run:
        return DryRunResult(ok=True, dry_run=True, number=number, pages=pages, tif=effective_tif)

    cli_cmd = f"channel originate PJSIP/{number}@{TRUNK} application SendFax {effective_tif},f"
    before_reading = transport.asterisk("fax show stats")
    before_ok = before_reading.ok
    before = ast_mod.parse_stats(before_reading.text) if before_ok else {}
    originate_reading = transport.asterisk(cli_cmd)
    if not originate_reading.ok:
        raise SendError(f"originate failed: {originate_reading.why}")
    out_text = originate_reading.text.strip()

    job_result: dict | None = None

    if wait:
        import time  # noqa: PLC0415

        end = time.time() + wait
        time.sleep(4)
        while time.time() < end:
            ch_reading = transport.asterisk("core show channels concise")
            if not ast_mod.trunk_channel_up(ch_reading.text, TRUNK):
                break
            time.sleep(3)
        after_reading = transport.asterisk("fax show stats")
        after = ast_mod.parse_stats(after_reading.text) if after_reading.ok else {}
        res = outcome_mod.judge(before, after, before_ok=before_ok, after_ok=after_reading.ok)
        tz = os.environ.get("FAX_TZ", "America/Los_Angeles")
        for row in cdr_mod.fax_rows(
            cdr_mod.parse_cdr(transport.read_cdr(100).text, 100), tz
        ):
            file_field = row.get("file", "")
            if file_field and effective_tif.endswith(file_field):
                res.update({k: row[k] for k in ("start", "answer", "end", "billsec", "disposition")})
                break
        job_result = res

    return SendResult(
        ok=True,
        number=number,
        label=resolved_label,
        pages=pages,
        tif=effective_tif,
        originate=out_text,
        started=dt.datetime.now().isoformat(timespec="seconds"),  # noqa: DTZ005
        result=job_result,
    )
