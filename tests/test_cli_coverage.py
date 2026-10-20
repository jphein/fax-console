"""tests/test_cli_coverage.py — edge-path coverage for faxcli.cli.

Targets lines untouched by the existing suite:
  - cmd_status human-readable output (lines 96-112, including warning)
  - cmd_log CDR failure with plain output (line 128), human-readable path (139-152)
  - cmd_send InvalidNumber exit (179-180), human-readable dry_run (188-192),
    human-readable send with wait result (195-200), human-readable send without wait (201-202)
  - cmd_test test-page not found (230-241), default page fallback (232-234), default wait (242-243)
"""
from __future__ import annotations

import io
import json
from pathlib import Path

from faxcli.cli import main
from faxcli.transport import Reading, ReplayTransport

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# cmd_status — human-readable output
# ---------------------------------------------------------------------------

class TestCmdStatusHumanReadable:
    def test_human_readable_ok_status(self):
        """Status without --json must print spandsp/trunk/gs summary to stdout."""
        buf = io.StringIO()
        rc = main(["status"], transport=ReplayTransport(), stdout=buf)
        assert rc == 0
        out = buf.getvalue()
        assert "spandsp" in out
        assert "trunk registered" in out
        assert "ghostscript" in out

    def test_human_readable_shows_stats(self):
        """Human-readable status must print sent/completed/failed counters."""
        buf = io.StringIO()
        main(["status"], transport=ReplayTransport(), stdout=buf)
        out = buf.getvalue()
        assert "attempted" in out
        assert "completed" in out
        assert "failed" in out

    def test_human_readable_warning_when_reads_fail(self):
        """When some readings fail, the human-readable output must print a WARNING line."""
        fail_cmds = {
            "fax show stats", "fax show sessions",
            "pjsip show endpoint voipms-fax", "pjsip show registrations",
            "pjsip show endpoint 2007", "module show like res_fax",
        }
        buf = io.StringIO()
        rc = main(
            ["status"],
            transport=ReplayTransport(fail_commands=fail_cmds),
            stdout=buf,
        )
        assert rc == 0
        assert "WARNING" in buf.getvalue()

    def test_human_readable_no_warning_on_success(self):
        """On a healthy PBX, the human-readable output must not print WARNING."""
        buf = io.StringIO()
        main(["status"], transport=ReplayTransport(), stdout=buf)
        assert "WARNING" not in buf.getvalue()


# ---------------------------------------------------------------------------
# cmd_log — CDR failure with plain output; human-readable path
# ---------------------------------------------------------------------------

class TestCmdLogHumanReadable:
    def test_cdr_failure_plain_output(self):
        """When the CDR read fails and --json is not set, print an error line to stdout."""
        buf = io.StringIO()
        rc = main(
            ["log"],
            transport=ReplayTransport(fail_cdr=True),
            stdout=buf,
        )
        assert rc == 1
        assert "error reading CDR" in buf.getvalue()

    def test_cdr_failure_json_output(self):
        """When the CDR read fails and --json is set, emit ok=False JSON."""
        buf = io.StringIO()
        rc = main(
            ["--json", "log"],
            transport=ReplayTransport(fail_cdr=True),
            stdout=buf,
        )
        assert rc == 1
        obj = json.loads(buf.getvalue())
        assert obj["ok"] is False
        assert obj["rows"] == []

    def test_human_readable_log_shows_header(self):
        """Human-readable log must print a column header line."""
        buf = io.StringIO()
        rc = main(["log"], transport=ReplayTransport(), stdout=buf)
        assert rc == 0
        out = buf.getvalue()
        assert "started" in out
        assert "number" in out

    def test_human_readable_log_shows_cdr_note(self):
        """Human-readable log must print the ANSWERED-is-not-delivered note."""
        buf = io.StringIO()
        main(["log"], transport=ReplayTransport(), stdout=buf)
        out = buf.getvalue()
        assert "ANSWERED" in out

    def test_human_readable_log_empty_cdr(self, tmp_path):
        """When the CDR has no fax rows, print 'no fax calls in the CDR'."""
        empty_cdr = tmp_path / "empty.csv"
        empty_cdr.write_text("")
        buf = io.StringIO()
        rc = main(
            ["log"],
            transport=ReplayTransport(cdr_path=str(empty_cdr)),
            stdout=buf,
        )
        assert rc == 0
        assert "no fax calls in the CDR" in buf.getvalue()


# ---------------------------------------------------------------------------
# cmd_send — InvalidNumber exit
# ---------------------------------------------------------------------------

class TestCmdSendInvalidNumber:
    def test_invalid_number_returns_1(self, tmp_path):
        """An invalid phone number must cause cmd_send to return 1."""
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        # "911" is a blocked N11 code — InvalidNumber raised by normalize()
        rc = main(
            ["send", str(pdf), "19115550100"],
            transport=ReplayTransport(spool_dir=tmp_path),
        )
        assert rc == 1

    def test_too_short_number_returns_1(self, tmp_path):
        """A number that is too short must cause cmd_send to return 1."""
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        rc = main(
            ["send", str(pdf), "555"],
            transport=ReplayTransport(spool_dir=tmp_path),
        )
        assert rc == 1


# ---------------------------------------------------------------------------
# cmd_send — human-readable output
# ---------------------------------------------------------------------------

class TestCmdSendHumanReadable:
    def test_dry_run_human_readable(self, tmp_path):
        """Human-readable dry_run must mention 'dry run' and the page count."""
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        buf = io.StringIO()
        rc = main(
            ["send", str(pdf), "12025550142", "--dry-run"],
            transport=ReplayTransport(spool_dir=tmp_path),
            stdout=buf,
        )
        assert rc == 0
        out = buf.getvalue()
        assert "dry run" in out
        assert "not dialed" in out

    def test_send_no_wait_human_readable(self, tmp_path):
        """Without --wait, human-readable output shows dialing + 'fax log' hint."""
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        class ImmediateTransport(ReplayTransport):
            def asterisk(self, cmd: str) -> Reading:
                # Return immediately without waiting
                return Reading.success("")

        buf = io.StringIO()
        rc = main(
            ["send", str(pdf), "12025550142"],
            transport=ImmediateTransport(spool_dir=tmp_path),
            stdout=buf,
        )
        assert rc == 0
        out = buf.getvalue()
        assert "dialing" in out
        assert "fax log" in out

    def test_send_with_wait_and_result_human_readable(self, tmp_path, monkeypatch):
        """With --wait and a fax result, human-readable output shows outcome."""
        import faxcli.api as _api  # noqa: PLC0415
        from faxcli.models import SendResult as ModelSendResult  # noqa: PLC0415

        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        # Build a fake SendResult with the required fields
        _fake_result = ModelSendResult(
            ok=True,
            number="12025550142",
            label="test",
            pages=1,
            tif=str(tmp_path / "out.tif"),
            originate="channel originate PJSIP/voipms-fax application SendFAX out.tif,f",
            started="2026-09-27 03:58:40",
            result={"outcome": "SENT", "disposition": "ANSWERED", "billsec": 42},
        )

        monkeypatch.setattr(_api, "send", lambda *a, **kw: _fake_result)

        buf = io.StringIO()
        rc = main(
            ["send", str(pdf), "12025550142", "--wait", "5"],
            transport=ReplayTransport(spool_dir=tmp_path),
            stdout=buf,
        )
        assert rc == 0
        out = buf.getvalue()
        assert "SENT" in out
        assert "ANSWERED" in out


# ---------------------------------------------------------------------------
# cmd_test — test-page not found, default pdf path, default wait
# ---------------------------------------------------------------------------

class TestCmdTest:
    def test_missing_test_page_returns_1(self, tmp_path, monkeypatch):
        """cmd_test must return 1 when the test page is not found."""
        import faxcli.cli as _cli  # noqa: PLC0415

        # Point the default test page at a non-existent path
        monkeypatch.setattr(_cli, "_DEFAULT_TEST_PAGE", str(tmp_path / "no-such-page.pdf"))

        buf = io.StringIO()
        rc = main(
            ["test"],
            transport=ReplayTransport(spool_dir=tmp_path),
            stdout=buf,
        )
        assert rc == 1

    def test_explicit_pdf_overrides_default(self, tmp_path):
        """When --pdf is given and exists, cmd_test uses it instead of the default."""
        pdf = tmp_path / "explicit.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        buf = io.StringIO()
        rc = main(
            ["test", "--pdf", str(pdf), "--dry-run"],
            transport=ReplayTransport(spool_dir=tmp_path),
            stdout=buf,
        )
        assert rc == 0

    def test_default_wait_is_set_to_90(self, tmp_path, monkeypatch):
        """cmd_test must set wait=90 when the caller doesn't specify --wait."""
        import faxcli.cli as _cli  # noqa: PLC0415

        pdf = tmp_path / "page.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        monkeypatch.setattr(_cli, "_DEFAULT_TEST_PAGE", str(pdf))

        captured_waits = []

        def _capturing_send(a, transport, stdout):
            captured_waits.append(a.wait)
            # Return immediately — don't actually send
            return 0

        monkeypatch.setattr(_cli, "cmd_send", _capturing_send)

        main(["test"], transport=ReplayTransport(spool_dir=tmp_path), stdout=io.StringIO())
        assert captured_waits == [90]

    def test_explicit_wait_is_not_overwritten(self, tmp_path, monkeypatch):
        """cmd_test must NOT overwrite an explicit --wait value with 90.

        With the inverted condition ``if not (not a.wait):`` (i.e. ``if a.wait:``)
        the branch fires for any truthy wait value and overwrites it with 90.
        This test catches that mutation by asserting wait stays at 30.
        """
        import faxcli.cli as _cli  # noqa: PLC0415

        pdf = tmp_path / "page.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        monkeypatch.setattr(_cli, "_DEFAULT_TEST_PAGE", str(pdf))

        captured_waits = []

        def _capturing_send(a, transport, stdout):
            captured_waits.append(a.wait)
            return 0

        monkeypatch.setattr(_cli, "cmd_send", _capturing_send)

        main(
            ["test", "--wait", "30"],
            transport=ReplayTransport(spool_dir=tmp_path),
            stdout=io.StringIO(),
        )
        assert captured_waits == [30], (
            "explicit --wait 30 must be preserved; cmd_test must not overwrite it with 90"
        )
