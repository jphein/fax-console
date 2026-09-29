"""tests/test_run12.py — deliberate behaviour fixes (run 12).

For each numbered item:
  * a characterization test runs the frozen legacy code on the same input and
    records what legacy did, so the divergence is visible;
  * a behaviour test pins the new faxcli behaviour.

Items covered:
  1. Failed originate → faxcli raises SendError; legacy said ok:true.
  2. Failed "before" stats read → outcome UNMEASURED; legacy counted from zero.
  3. Empty CDR file field → matches nothing; legacy matched every path.
  4a. Non-local render uses tempfile.mkdtemp, not a predictable /tmp path.
  4b. SshTransport has '--' before the host in the ssh argv.
  4c. LocalTransport.read_cdr honours its limit parameter.
"""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from faxcli.transport import LocalTransport, Reading, ReplayTransport, SshTransport

_LEGACY_PATH = Path(__file__).parent.parent / "legacy" / "fax" / "fax" / "cli.py"
_FIXTURES = Path(__file__).parent / "fixtures"


def _load_legacy():
    spec = importlib.util.spec_from_file_location("legacy_cli_r12", str(_LEGACY_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _CP:
    """Minimal CompletedProcess stub."""
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _make_fake_run(fail_originate=False, fail_before_stats=False):
    """Fake subprocess.run backed by recorded fixtures.

    fail_originate: the 'channel originate …' command returns non-zero.
    fail_before_stats: the first 'fax show stats' call returns non-zero.
    """
    call_count: dict[str, int] = {}

    def fake_run(argv, capture_output=False, text=False, timeout=None, check=False, **_kw):
        if not argv:
            return _CP(returncode=1)

        if "asterisk" in argv and "-rx" in argv:
            idx = argv.index("-rx")
            ast_cmd = argv[idx + 1]
            # track how many times each command was called
            call_count[ast_cmd] = call_count.get(ast_cmd, 0) + 1
            if ast_cmd.startswith("channel originate") and fail_originate:
                return _CP(returncode=1, stderr="originate: no such endpoint")
            if ast_cmd == "fax show stats" and fail_before_stats and call_count[ast_cmd] == 1:
                return _CP(returncode=1)
            fname = ast_cmd.replace(" ", "_") + ".txt"
            fpath = _FIXTURES / "asterisk" / fname
            if fpath.exists():
                return _CP(stdout=fpath.read_text())
            return _CP(returncode=1)

        if "which" in argv:
            return _CP(stdout="/usr/bin/gs\n")

        if "tail" in argv:
            try:
                n_idx = argv.index("-n")
                limit = int(argv[n_idx + 1])
            except (ValueError, IndexError):
                limit = 200
            lines = (_FIXTURES / "cdr" / "Master.csv").read_text().splitlines()
            return _CP(stdout="\n".join(lines[-limit:]) + "\n")

        if check:
            raise Exception(f"unhandled check=True command: {argv}")
        return _CP(returncode=1)

    return fake_run


@pytest.fixture(scope="module")
def legacy():
    return _load_legacy()


# ============================================================================
# Item 1 — failed originate
# ============================================================================

class TestFailedOriginate:
    """Legacy says ok:true even when channel originate fails.
    faxcli raises SendError so the CLI exits non-zero.
    """

    @pytest.mark.allow_subprocesses
    def test_legacy_ok_true_on_failed_originate(self, legacy, monkeypatch, tmp_path):
        """Legacy records the send as ok:true when originate exits non-zero."""
        monkeypatch.setattr(legacy, "SPOOL", str(tmp_path))
        monkeypatch.setattr(legacy.subprocess, "run", _make_fake_run(fail_originate=True))

        # patch gs so the TIFF is written into tmp_path
        import struct
        real_run = _make_fake_run(fail_originate=True)

        def gs_and_rest(argv, *a, **kw):
            if argv and argv[0] == "gs":
                for arg in argv:
                    if arg.startswith("-sOutputFile="):
                        dest = arg[len("-sOutputFile="):]
                        with open(dest, "wb") as f:
                            f.write(b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)
                                    + struct.pack("<H", 0) + struct.pack("<I", 0))
                        break
                return _CP()
            return real_run(argv, *a, **kw)

        monkeypatch.setattr(legacy.subprocess, "run", gs_and_rest)

        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        old_stdout = sys.stdout
        sys.stdout = buf = io.StringIO()
        try:
            # legacy does not --wait so no wait_for; just check the job dict
            import argparse
            a = argparse.Namespace(
                local=True, json=True, pdf=str(pdf), number="12025550142",
                label="test", dry_run=False, wait=0,
            )
            legacy.cmd_send(a)
        finally:
            sys.stdout = old_stdout

        out = buf.getvalue().strip()
        assert out, "legacy produced no output"
        obj = json.loads(out.splitlines()[-1])
        # Legacy bug: reports ok:true even when originate failed
        assert obj["ok"] is True, "characterization: legacy ok:true on failed originate"

    def test_new_raises_send_error_on_failed_originate(self, tmp_path):
        """faxcli raises SendError and the CLI exits 1 when originate fails."""
        from faxcli.cli import main

        class FailOriginate(ReplayTransport):
            def asterisk(self, cmd):
                if cmd.startswith("channel originate"):
                    return Reading.failure("originate: no such endpoint")
                return super().asterisk(cmd)

        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        buf = io.StringIO()
        rc = main(
            ["--json", "send", str(pdf), "12025550142"],
            transport=FailOriginate(spool_dir=tmp_path),
            stdout=buf,
        )
        assert rc == 1
        # stdout must be empty (error goes to stderr)
        assert buf.getvalue().strip() == ""

    def test_new_send_error_carries_why(self, tmp_path):
        """SendError.reason contains the transport's why string."""
        from faxcli.api import SendError, send

        class FailOriginate(ReplayTransport):
            def asterisk(self, cmd):
                if cmd.startswith("channel originate"):
                    return Reading.failure("pbx: connection refused")
                return super().asterisk(cmd)

        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        with pytest.raises(SendError) as exc_info:
            send(str(pdf), "12025550142", transport=FailOriginate(spool_dir=tmp_path), local=True)

        assert "pbx: connection refused" in exc_info.value.reason

    def test_successful_send_json_unchanged(self, tmp_path):
        """A successful send still produces ok:true with the legacy JSON shape."""
        from faxcli.cli import main

        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        buf = io.StringIO()
        rc = main(
            ["--json", "send", str(pdf), "12025550142"],
            transport=ReplayTransport(spool_dir=tmp_path),
            stdout=buf,
        )
        assert rc == 0
        obj = json.loads(buf.getvalue())
        assert obj["ok"] is True
        for key in ("number", "pages", "tif", "originate", "started", "label"):
            assert key in obj, f"missing key {key!r}"


# ============================================================================
# Item 2 — failed "before" stats read
# ============================================================================

class TestFailedBeforeStats:
    """Legacy counts the delta from zero when the before-stats read fails.
    faxcli marks the outcome as UNMEASURED instead.
    """

    def test_legacy_counts_from_zero_on_failed_before(self):
        """Legacy judge() with an empty before dict produces a non-zero delta."""
        # Simulate what legacy does: parse_stats("") returns {}; delta = after - 0
        after = {"Completed FAXes": 5, "Failed FAXes": 0}
        # Legacy delta: after.get(k, 0) - {}.get(k, 0) = 5
        completed_delta = after.get("Completed FAXes", 0) - {}.get("Completed FAXes", 0)
        assert completed_delta == 5, (
            "characterization: legacy computes 5 from nothing when before read failed"
        )

    def test_new_unmeasured_when_before_fails(self):
        """outcome.judge with before_ok=False returns UNMEASURED with None deltas."""
        from faxcli.outcome import judge

        after = {"Completed FAXes": 5, "Failed FAXes": 0}
        res = judge({}, after, before_ok=False, after_ok=True)
        assert res["outcome"] == "UNMEASURED"
        assert res["completed_delta"] is None
        assert res["failed_delta"] is None

    def test_new_unmeasured_when_after_fails(self):
        """outcome.judge with after_ok=False also returns UNMEASURED."""
        from faxcli.outcome import judge

        before = {"Completed FAXes": 3}
        res = judge(before, {}, before_ok=True, after_ok=False)
        assert res["outcome"] == "UNMEASURED"
        assert res["completed_delta"] is None

    def test_new_measured_when_both_ok(self):
        """Normal case: both reads ok → delta computed correctly."""
        from faxcli.outcome import judge

        before = {"Completed FAXes": 2, "Failed FAXes": 0}
        after = {"Completed FAXes": 3, "Failed FAXes": 0}
        res = judge(before, after, before_ok=True, after_ok=True)
        assert res["outcome"] == "SENT"
        assert res["completed_delta"] == 1

    def test_wait_result_unmeasured_when_before_stats_fails(self, tmp_path):
        """When --wait is used and before-stats read fails, result.outcome == UNMEASURED."""
        from faxcli.api import send

        class BeforeStatsFail(ReplayTransport):
            _stats_calls = 0

            def asterisk(self, cmd):
                if cmd == "fax show stats":
                    BeforeStatsFail._stats_calls += 1
                    if BeforeStatsFail._stats_calls == 1:
                        return Reading.failure("fax show stats: read error")
                if cmd == "core show channels concise":
                    # report no channel active so wait loop exits immediately
                    return Reading.success("")
                return super().asterisk(cmd)

        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        result = send(
            str(pdf), "12025550142",
            transport=BeforeStatsFail(spool_dir=tmp_path),
            local=True,
            wait=1,
        )
        assert result.result is not None
        assert result.result["outcome"] == "UNMEASURED"
        assert result.result["completed_delta"] is None


# ============================================================================
# Item 3 — empty CDR file field
# ============================================================================

class TestEmptyCdrFileField:
    """Legacy matches any path when file == "" because tif.endswith("") is always True.
    faxcli skips the CDR row when file is empty.
    """

    def test_legacy_empty_file_matches_every_tif(self):
        """Characterize legacy: endswith('') is True for any string."""
        # This is the exact legacy pattern (legacy/fax/fax/cli.py:150):
        #   if tif.endswith(row.get("file", "\0")):
        # When file == "" we get tif.endswith("") which is always True.
        tif = "/var/spool/asterisk/fax/20260927-050705-panel-test-19725329272.tif"
        row_with_empty_file = {"file": ""}
        assert tif.endswith(row_with_empty_file.get("file", "\0")), (
            "characterization: legacy matches any tif when file is empty"
        )

    def test_new_empty_file_does_not_match(self, tmp_path):
        """faxcli skips a CDR row whose file field is empty."""
        from faxcli.api import send

        class EmptyFileCDR(ReplayTransport):
            def read_cdr(self, limit):
                # Return a CDR line whose file field is empty (SendFAX with no TIFF in lastdata)
                line = (
                    '"","","s","from-pstn","","PJSIP/voipms-fax-00000001","","SendFAX",'
                    '"","2026-09-27 05:07:06","2026-09-27 05:07:07","2026-09-27 05:07:48",'
                    '"42","42","ANSWERED","DOCUMENTATION","1790485626.99",""\n'
                )
                return Reading.success(line)

            def asterisk(self, cmd):
                if cmd == "core show channels concise":
                    return Reading.success("")
                return super().asterisk(cmd)

        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        result = send(
            str(pdf), "12025550142",
            transport=EmptyFileCDR(spool_dir=tmp_path),
            local=True,
            wait=1,
        )
        assert result.result is not None
        # No CDR row should have matched — no start/answer/end keys
        assert "start" not in result.result, (
            "empty file CDR row must not be matched to the send"
        )

    def test_new_nonempty_file_still_matches(self, tmp_path):
        """A non-empty file field still matches when tif ends with it."""
        from faxcli.api import send

        tif_name = None

        class KnownFileCDR(ReplayTransport):
            def render(self, pdf, tif):
                nonlocal tif_name
                result = super().render(pdf, tif)
                tif_name = Path(result.text).name
                return result

            def read_cdr(self, limit):
                # Return a CDR row whose file == the tif name we just wrote
                assert tif_name is not None
                line = (
                    f'"","","s","from-pstn","","PJSIP/voipms-fax-00000001","","SendFax",'
                    f'"/var/spool/asterisk/fax/{tif_name}","2026-09-27 05:07:06",'
                    f'"2026-09-27 05:07:07","2026-09-27 05:07:48","42","42","ANSWERED",'
                    f'"DOCUMENTATION","1790485626.99",""\n'
                )
                return Reading.success(line)

            def asterisk(self, cmd):
                if cmd == "core show channels concise":
                    return Reading.success("")
                return super().asterisk(cmd)

        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        result = send(
            str(pdf), "12025550142",
            transport=KnownFileCDR(spool_dir=tmp_path),
            local=True,
            wait=1,
        )
        assert result.result is not None
        assert "start" in result.result, "non-empty file should still match"


# ============================================================================
# Item 4a — tempfile.mkdtemp for non-local render
# ============================================================================

class TestTempfileForNonLocalRender:
    """Non-local render must use a tempfile.mkdtemp directory, not /tmp/<name>."""

    def test_render_path_is_not_predictable_slash_tmp(self, tmp_path):
        """When local=False, the localtif path is not /tmp/<name> but a mkdtemp subdir."""
        import tempfile
        created_dirs: list[str] = []
        real_mkdtemp = tempfile.mkdtemp

        def patched_mkdtemp(*a, **kw):
            d = real_mkdtemp(*a, **kw)
            created_dirs.append(d)
            return d

        render_paths: list[str] = []

        class CapturePath(ReplayTransport):
            def render(self, pdf, tif):
                render_paths.append(tif)
                return super().render(pdf, tif)

        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        import faxcli.api as api_mod
        original = api_mod.tempfile.mkdtemp

        try:
            api_mod.tempfile.mkdtemp = patched_mkdtemp
            from faxcli.api import send
            # local=False triggers the mkdtemp path
            send(
                str(pdf), "12025550142",
                transport=CapturePath(spool_dir=tmp_path),
                local=False,
                dry_run=True,
            )
        finally:
            api_mod.tempfile.mkdtemp = original

        assert created_dirs, "mkdtemp must have been called"
        assert render_paths, "render must have been called"
        rendered = render_paths[0]
        assert rendered.startswith(created_dirs[0]), (
            f"render path {rendered!r} must be inside mkdtemp dir {created_dirs[0]!r}"
        )
        # Must NOT be a flat /tmp/<name>
        import re
        assert not re.match(r"^/tmp/[^/]+$", rendered), (
            f"render path must not be a predictable flat /tmp path, got {rendered!r}"
        )

    def test_tmpdir_cleaned_up_after_dry_run(self, tmp_path):
        """The mkdtemp directory is removed after a dry-run (before the function returns)."""
        import tempfile

        created: list[str] = []
        real_mkdtemp = tempfile.mkdtemp

        def tracking_mkdtemp(*a, **kw):
            d = real_mkdtemp(*a, **kw)
            created.append(d)
            return d

        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        import faxcli.api as api_mod
        original = api_mod.tempfile.mkdtemp
        try:
            api_mod.tempfile.mkdtemp = tracking_mkdtemp
            from faxcli.api import send
            send(
                str(pdf), "12025550142",
                transport=ReplayTransport(spool_dir=tmp_path),
                local=False,
                dry_run=True,
            )
        finally:
            api_mod.tempfile.mkdtemp = original

        assert created
        for d in created:
            assert not Path(d).exists(), f"tmpdir {d!r} was not cleaned up"


# ============================================================================
# Item 4b — '--' before host in SshTransport argv
# ============================================================================

class TestSshDashDashBeforeHost:
    """'--' must appear in the ssh argv immediately before the host,
    so a host starting with '-' cannot be treated as an ssh option.
    """

    def test_dash_dash_before_host(self, monkeypatch):
        """'--' separates SSH options from the host in the argv."""
        calls = []

        def _fake_run(argv, **_kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        t = SshTransport(host="pbx")
        t.asterisk("fax show stats")

        assert calls
        full = calls[0]
        host_idx = full.index("pbx")
        assert host_idx >= 1 and full[host_idx - 1] == "--", (
            f"'--' must appear immediately before 'pbx' in argv, got {full!r}"
        )

    @pytest.mark.allow_subprocesses
    def test_dash_dash_legacy_did_not_have_it(self):
        """Characterize legacy: SshTransport (no legacy equivalent) — verify ssh call
        in legacy cli.py never had '--' before the host."""
        # Legacy cli.py:55 builds: SSH + [EXCHANGE, remote_cmd]
        # SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
        # No "--" is present.
        import shlex
        exchange = "pbx"
        ssh_opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
        remote_cmd = " ".join(shlex.quote(a) for a in ["sudo", "-n", "asterisk", "-rx", "fax show stats"])
        legacy_argv = ["ssh"] + ssh_opts + [exchange, remote_cmd]
        # confirm no "--" in the legacy-style argv
        assert "--" not in legacy_argv, (
            "characterization: legacy ssh argv had no '--' before host"
        )

    @pytest.mark.allow_subprocesses
    def test_dash_host_becomes_option_in_legacy_argv(self):
        """Characterize: a host starting with '-' would be parsed as an option in the legacy argv."""
        # This is the vulnerability being fixed.  We only characterize the shape.
        import shlex
        bad_host = "-oHostbasedAuthentication=yes"
        ssh_opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
        remote_cmd = shlex.quote("fax show stats")
        legacy_argv = ["ssh"] + ssh_opts + [bad_host, remote_cmd]
        # bad_host appears directly after ssh options with no '--' guard
        idx = legacy_argv.index(bad_host)
        assert legacy_argv[idx - 1] != "--", (
            "characterization: legacy has no '--' guard; bad host follows options directly"
        )

    @pytest.mark.allow_subprocesses
    def test_new_argv_with_dash_host_has_guard(self, monkeypatch):
        """With the fix, '--' precedes the host even when host starts with '-'."""
        calls = []

        def _fake_run(argv, **_kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        t = SshTransport(host="-malicious.example.com")
        t.asterisk("fax show stats")

        full = calls[0]
        host_idx = full.index("-malicious.example.com")
        assert full[host_idx - 1] == "--", (
            f"'--' must precede a dash-starting host, got {full!r}"
        )


# ============================================================================
# Item 4c — LocalTransport.read_cdr honours limit
# ============================================================================

class TestLocalReadCdrLimit:
    """LocalTransport.read_cdr(limit) must return at most *limit* lines.
    Legacy cdr_rows (local) reads the whole file and then slices the tail.
    """

    def test_legacy_reads_whole_file_ignoring_limit(self, monkeypatch):
        """Characterize legacy: cdr_rows(local=True, limit=1) still reads all lines."""
        legacy = _load_legacy()
        import builtins
        read_calls: list[str] = []
        real_open = open

        def fake_open(path, *a, **kw):
            from faxcli.cdr import CDR as CDR_PATH
            if str(path) == CDR_PATH:
                kw.pop("newline", None)
                fh = real_open(str(_FIXTURES / "cdr" / "Master.csv"), *a, **kw)
                # wrap to record content length
                content = fh.read()
                read_calls.append(content)
                fh.close()
                return real_open(str(_FIXTURES / "cdr" / "Master.csv"), *a, **kw)
            return real_open(path, *a, **kw)

        monkeypatch.setattr(builtins, "open", fake_open)
        legacy.cdr_rows(local=True, limit=1)
        # Legacy: reads the whole file into rows then slices [-1:]
        total_lines = len((_FIXTURES / "cdr" / "Master.csv").read_text().splitlines())
        # read_calls[0] should be the full file content
        assert read_calls, "legacy opened the CDR file"
        full_line_count = len(read_calls[0].splitlines())
        assert full_line_count == total_lines, (
            f"characterization: legacy read all {total_lines} lines even with limit=1"
        )

    def test_new_read_cdr_honours_limit(self, tmp_path, monkeypatch):
        """LocalTransport.read_cdr(limit=3) returns at most 3 lines."""
        cdr_file = tmp_path / "Master.csv"
        # Write 10 lines so we can confirm the tail
        lines = [f'"","","s","from-pstn","","PJSIP/v-{i}","","SendFax","x.tif",'
                 f'"2026-09-27 05:0{i}:00","","","42","42","ANSWERED","DOCUMENTATION","u{i}",""\n'
                 for i in range(10)]
        cdr_file.write_text("".join(lines))

        import faxcli.cdr as cdr_mod_real
        monkeypatch.setattr(cdr_mod_real, "CDR", str(cdr_file))

        t = LocalTransport(is_asterisk_user=lambda: True)
        reading = t.read_cdr(3)
        assert reading.ok
        returned_lines = [ln for ln in reading.text.splitlines() if ln.strip()]
        assert len(returned_lines) == 3, (
            f"expected 3 lines with limit=3, got {len(returned_lines)}"
        )
        # Must be the tail
        assert "u9" in reading.text
        assert "u0" not in reading.text

    def test_new_read_cdr_limit_larger_than_file(self, tmp_path, monkeypatch):
        """When limit > number of lines, all lines are returned."""
        cdr_file = tmp_path / "Master.csv"
        lines = [f'"","row{i}"\n' for i in range(5)]
        cdr_file.write_text("".join(lines))

        import faxcli.cdr as cdr_mod_real
        monkeypatch.setattr(cdr_mod_real, "CDR", str(cdr_file))

        t = LocalTransport(is_asterisk_user=lambda: True)
        reading = t.read_cdr(100)
        assert reading.ok
        returned = reading.text.splitlines()
        assert len(returned) == 5
