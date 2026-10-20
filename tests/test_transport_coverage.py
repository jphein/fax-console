"""tests/test_transport_coverage.py — edge-path coverage for faxcli.transport.

Targets lines untouched by the existing suite:
  - _default_is_asterisk_user (exception branch)
  - LocalTransport.asterisk non-zero returncode, generic Exception
  - LocalTransport.read_cdr OSError
  - LocalTransport.which_gs (timeout, generic Exception)
  - LocalTransport.render (success, timeout, CalledProcessError, generic Exception)
  - LocalTransport.spool (trivial success)
  - LocalTransport.cleanup (no-op)
  - SshTransport._ssh generic Exception
  - SshTransport.read_cdr (delegates to _ssh)
  - SshTransport.which_gs (delegates to _ssh)
  - SshTransport.render (timeout, CalledProcessError, generic Exception)
  - SshTransport.spool timeout, CalledProcessError, generic Exception
  - SshTransport.cleanup (removes the local file)
  - ReplayTransport.which_gs missing fixture fallback
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from faxcli.transport import (
    LocalTransport,
    ReplayTransport,
    SshTransport,
    _default_is_asterisk_user,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# _default_is_asterisk_user
# ---------------------------------------------------------------------------

class TestDefaultIsAsteriskUser:
    def test_returns_bool(self):
        """Must return a bool without raising."""
        result = _default_is_asterisk_user()
        assert isinstance(result, bool)

    def test_exception_returns_false(self, monkeypatch):
        """If os.geteuid raises, the function must return False (not propagate)."""
        def _raise():
            raise OSError("no uid")

        monkeypatch.setattr(os, "geteuid", _raise)
        assert _default_is_asterisk_user() is False


# ---------------------------------------------------------------------------
# LocalTransport.asterisk — non-zero returncode and generic Exception
# ---------------------------------------------------------------------------

class TestLocalTransportAsterisk:
    @pytest.mark.allow_subprocesses
    def test_non_zero_returncode_is_failure(self, monkeypatch):
        """A non-zero exit code must produce a failed Reading."""
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: subprocess.CompletedProcess(a[0], returncode=1, stdout=""))
        t = LocalTransport(is_asterisk_user=lambda: True)
        r = t.asterisk("fax show stats")
        assert not r.ok
        assert "exited 1" in r.why

    @pytest.mark.allow_subprocesses
    def test_generic_exception_is_failure(self, monkeypatch):
        """Any unexpected exception must become a failed Reading."""
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("oops")))
        t = LocalTransport(is_asterisk_user=lambda: True)
        r = t.asterisk("fax show stats")
        assert not r.ok
        assert "oops" in r.why


# ---------------------------------------------------------------------------
# LocalTransport.read_cdr — OSError branch
# ---------------------------------------------------------------------------

class TestLocalTransportReadCdr:
    def test_oserror_is_failure(self, monkeypatch, tmp_path):
        """When the CDR file cannot be opened, read_cdr must return a failure."""
        import faxcli.cdr as _cdr  # noqa: PLC0415

        # Point CDR at a path that does not exist
        monkeypatch.setattr(_cdr, "CDR", str(tmp_path / "no_such_file.csv"))
        t = LocalTransport()
        r = t.read_cdr(10)
        assert not r.ok
        assert r.why  # some OS error message

    def test_limit_zero_returns_empty(self, monkeypatch, tmp_path):
        """limit=0 must return an empty-text success without opening the file."""
        import faxcli.cdr as _cdr  # noqa: PLC0415

        monkeypatch.setattr(_cdr, "CDR", str(tmp_path / "no_such_file.csv"))
        t = LocalTransport()
        r = t.read_cdr(0)
        assert r.ok
        assert r.text == ""


# ---------------------------------------------------------------------------
# LocalTransport.which_gs — timeout and generic Exception
# ---------------------------------------------------------------------------

class TestLocalTransportWhichGs:
    @pytest.mark.allow_subprocesses
    def test_success_returns_path(self, monkeypatch):
        """which_gs must return the path when `which gs` succeeds."""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], returncode=0, stdout="/usr/bin/gs\n"),
        )
        t = LocalTransport()
        r = t.which_gs()
        assert r.ok
        assert r.text == "/usr/bin/gs"

    @pytest.mark.allow_subprocesses
    def test_not_found_is_failure(self, monkeypatch):
        """which gs returning non-zero (gs not on PATH) must be a failure."""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], returncode=1, stdout=""),
        )
        t = LocalTransport()
        r = t.which_gs()
        assert not r.ok
        assert "not found" in r.why

    @pytest.mark.allow_subprocesses
    def test_timeout_is_failure(self, monkeypatch):
        """TimeoutExpired from `which gs` must become a failed Reading."""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("which", 10)),
        )
        t = LocalTransport()
        r = t.which_gs()
        assert not r.ok
        assert "timed out" in r.why

    @pytest.mark.allow_subprocesses
    def test_generic_exception_is_failure(self, monkeypatch):
        """Any unexpected exception from `which gs` must become a failed Reading."""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("which broke")),
        )
        t = LocalTransport()
        r = t.which_gs()
        assert not r.ok
        assert "which broke" in r.why


# ---------------------------------------------------------------------------
# LocalTransport.render — success, timeout, CalledProcessError, generic Exception
# ---------------------------------------------------------------------------

class TestLocalTransportRender:
    @pytest.mark.allow_subprocesses
    def test_success_returns_tif_path(self, monkeypatch, tmp_path):
        """A successful gs run must return the tif path as a success Reading."""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], returncode=0),
        )
        t = LocalTransport()
        tif = str(tmp_path / "out.tif")
        r = t.render("doc.pdf", tif)
        assert r.ok
        assert r.text == tif

    @pytest.mark.allow_subprocesses
    def test_timeout_is_failure(self, monkeypatch):
        """gs timeout must become a failed Reading."""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("gs", 120)),
        )
        t = LocalTransport()
        r = t.render("doc.pdf", "/tmp/out.tif")
        assert not r.ok
        assert "timed out" in r.why

    @pytest.mark.allow_subprocesses
    def test_called_process_error_is_failure(self, monkeypatch):
        """gs CalledProcessError must become a failed Reading."""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (_ for _ in ()).throw(
                subprocess.CalledProcessError(1, "gs")
            ),
        )
        t = LocalTransport()
        r = t.render("doc.pdf", "/tmp/out.tif")
        assert not r.ok
        assert "gs failed" in r.why

    @pytest.mark.allow_subprocesses
    def test_generic_exception_is_failure(self, monkeypatch):
        """Any unexpected exception from gs must become a failed Reading."""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("no gs")),
        )
        t = LocalTransport()
        r = t.render("doc.pdf", "/tmp/out.tif")
        assert not r.ok
        assert "no gs" in r.why


# ---------------------------------------------------------------------------
# LocalTransport.spool and cleanup — trivial no-ops
# ---------------------------------------------------------------------------

class TestLocalTransportSpoolCleanup:
    def test_spool_returns_spooled_path(self):
        """LocalTransport.spool is a no-op that returns the spooled path."""
        t = LocalTransport()
        r = t.spool("/tmp/x.tif", "x.tif", "/var/spool/asterisk/fax/x.tif")
        assert r.ok
        assert r.text == "/var/spool/asterisk/fax/x.tif"

    def test_cleanup_is_noop(self):
        """LocalTransport.cleanup does nothing (no exception)."""
        t = LocalTransport()
        t.cleanup("/tmp/nonexistent.tif")  # must not raise


# ---------------------------------------------------------------------------
# SshTransport._ssh — generic Exception branch
# ---------------------------------------------------------------------------

class TestSshTransportGenericException:
    @pytest.mark.allow_subprocesses
    def test_generic_exception_is_failure(self, monkeypatch):
        """An unexpected exception from subprocess.run must become a failed Reading."""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("connection refused")),
        )
        t = SshTransport(host="pbx.example.com")
        r = t.asterisk("fax show stats")
        assert not r.ok
        assert "connection refused" in r.why


# ---------------------------------------------------------------------------
# SshTransport.read_cdr — delegates to _ssh
# ---------------------------------------------------------------------------

class TestSshTransportReadCdr:
    @pytest.mark.allow_subprocesses
    def test_read_cdr_uses_ssh(self, monkeypatch):
        """SshTransport.read_cdr must call ssh with sudo tail -n."""
        calls = []

        def _fake_run(argv, **kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, returncode=0, stdout="row1\nrow2\n")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        t = SshTransport(host="pbx.example.com")
        r = t.read_cdr(5)
        assert r.ok
        assert calls
        remote_cmd = calls[0][-1]  # the quoted remote command string
        assert "tail" in remote_cmd

    @pytest.mark.allow_subprocesses
    def test_read_cdr_ssh_failure_is_failure(self, monkeypatch):
        """A failed ssh in read_cdr must produce a failed Reading."""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], returncode=255,
                                                          stdout="", stderr="no route"),
        )
        t = SshTransport(host="pbx.example.com")
        r = t.read_cdr(10)
        assert not r.ok


# ---------------------------------------------------------------------------
# SshTransport.which_gs
# ---------------------------------------------------------------------------

class TestSshTransportWhichGs:
    @pytest.mark.allow_subprocesses
    def test_which_gs_uses_ssh(self, monkeypatch):
        """SshTransport.which_gs must call ssh with 'which gs'."""
        calls = []

        def _fake_run(argv, **kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, returncode=0, stdout="/usr/bin/gs\n")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        t = SshTransport(host="pbx.example.com")
        r = t.which_gs()
        assert r.ok
        assert calls
        remote_cmd = calls[0][-1]
        assert "which" in remote_cmd and "gs" in remote_cmd


# ---------------------------------------------------------------------------
# SshTransport.render — timeout, CalledProcessError, generic Exception
# (render always runs gs locally, even for SshTransport)
# ---------------------------------------------------------------------------

class TestSshTransportRender:
    @pytest.mark.allow_subprocesses
    def test_success(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], returncode=0),
        )
        t = SshTransport(host="pbx.example.com")
        r = t.render("doc.pdf", str(tmp_path / "out.tif"))
        assert r.ok

    @pytest.mark.allow_subprocesses
    def test_timeout_is_failure(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("gs", 120)),
        )
        t = SshTransport(host="pbx.example.com")
        r = t.render("doc.pdf", "/tmp/out.tif")
        assert not r.ok
        assert "timed out" in r.why

    @pytest.mark.allow_subprocesses
    def test_called_process_error_is_failure(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "gs")),
        )
        t = SshTransport(host="pbx.example.com")
        r = t.render("doc.pdf", "/tmp/out.tif")
        assert not r.ok
        assert "gs failed" in r.why

    @pytest.mark.allow_subprocesses
    def test_generic_exception_is_failure(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("gs missing")),
        )
        t = SshTransport(host="pbx.example.com")
        r = t.render("doc.pdf", "/tmp/out.tif")
        assert not r.ok
        assert "gs missing" in r.why


# ---------------------------------------------------------------------------
# SshTransport.spool — timeout, CalledProcessError, generic Exception on scp
# ---------------------------------------------------------------------------

class TestSshTransportSpoolEdgePaths:
    @pytest.mark.allow_subprocesses
    def test_scp_timeout_is_failure(self, monkeypatch, tmp_path):
        """scp timeout must produce a failed Reading without calling install."""
        calls = []

        def _fake_run(argv, **kw):
            calls.append(argv)
            if argv[0] == "scp":
                raise subprocess.TimeoutExpired("scp", 60)
            return subprocess.CompletedProcess(argv, returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        tif = tmp_path / "x.tif"
        tif.write_bytes(b"II")
        r = SshTransport(host="pbx.example.com").spool(str(tif), "x.tif", "/var/spool/asterisk/fax/x.tif")
        assert not r.ok
        assert "scp timed out" in r.why

    @pytest.mark.allow_subprocesses
    def test_scp_called_process_error_is_failure(self, monkeypatch, tmp_path):
        """scp CalledProcessError must produce a failed Reading."""

        def _fake_run(argv, **kw):
            if argv[0] == "scp":
                raise subprocess.CalledProcessError(1, "scp")
            return subprocess.CompletedProcess(argv, returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        tif = tmp_path / "x.tif"
        tif.write_bytes(b"II")
        r = SshTransport(host="pbx.example.com").spool(str(tif), "x.tif", "/var/spool/asterisk/fax/x.tif")
        assert not r.ok
        assert "scp failed" in r.why

    @pytest.mark.allow_subprocesses
    def test_scp_generic_exception_is_failure(self, monkeypatch, tmp_path):
        """An unexpected exception from scp must produce a failed Reading."""

        def _fake_run(argv, **kw):
            if argv[0] == "scp":
                raise OSError("no scp")
            return subprocess.CompletedProcess(argv, returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        tif = tmp_path / "x.tif"
        tif.write_bytes(b"II")
        r = SshTransport(host="pbx.example.com").spool(str(tif), "x.tif", "/var/spool/asterisk/fax/x.tif")
        assert not r.ok
        assert "no scp" in r.why


# ---------------------------------------------------------------------------
# SshTransport.cleanup — removes the local file
# ---------------------------------------------------------------------------

class TestSshTransportCleanup:
    def test_removes_local_file(self, tmp_path):
        """cleanup must delete the local TIFF."""
        f = tmp_path / "tmp.tif"
        f.write_bytes(b"II")
        t = SshTransport(host="pbx.example.com")
        t.cleanup(str(f))
        assert not f.exists()

    def test_missing_file_does_not_raise(self, tmp_path):
        """cleanup on a non-existent file must not raise."""
        t = SshTransport(host="pbx.example.com")
        t.cleanup(str(tmp_path / "gone.tif"))  # must not raise


# ---------------------------------------------------------------------------
# ReplayTransport.which_gs — missing fixture falls back to failure
# ---------------------------------------------------------------------------

class TestReplayTransportWhichGsMissing:
    def test_missing_fixture_is_failure(self, tmp_path):
        """When which_gs.txt is absent, which_gs must return a failure Reading."""
        # tmp_path has no which_gs.txt
        t = ReplayTransport(fixture_dir=tmp_path)
        r = t.which_gs()
        assert not r.ok
        assert "no recorded" in r.why
