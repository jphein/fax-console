"""Tests for transport fixes and send-path behaviour (items 1–4 of the review).

Covers:
  1. SshTransport._ssh quotes every remote argument with shlex.quote.
  2. LocalTransport skips sudo when the effective user is 'asterisk'.
  3. The PBX hostname is taken from FAX_EXCHANGE_HOST / 'pbx' default.
  4. send --dry-run goes through the transport seam (ReplayTransport writes
     the TIFF into the test's tmp_path and prints the legacy dry-run shape).
  5. TimeoutExpired in the transport becomes a failed Reading (not an exception).
"""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from faxcli.transport import (
    EXCHANGE,
    LocalTransport,
    ReplayTransport,
    SshTransport,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# 1. SshTransport — remote command quoting
# ---------------------------------------------------------------------------

class TestSshTransportQuoting:
    """The remote command must arrive as one quoted shell word per argument.

    Legacy reference: legacy/fax/fax/cli.py:55 — shlex.quote every element
    before joining them into a single remote shell argument.
    """

    @pytest.mark.allow_subprocesses
    def test_fax_show_stats_is_one_quoted_argument(self, monkeypatch):
        """'asterisk -rx fax show stats' must be one single-quoted remote arg."""
        calls = []

        def _fake_run(argv, **_kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        t = SshTransport(host="pbx")
        t.asterisk("fax show stats")

        assert calls, "subprocess.run was not called"
        full = calls[0]
        # last element is the remote command string passed to the shell
        remote = full[-1]
        # must be ONE argument (no bare spaces outside quotes)
        # shlex.quote produces 'sudo' '-n' 'asterisk' '-rx' 'fax show stats'
        # joined with spaces, but each token individually quoted
        assert "'fax show stats'" in remote, (
            f"Expected 'fax show stats' to be quoted as one token, got: {remote!r}"
        )
        # Must not split the Asterisk command into separate words
        assert remote != "sudo -n asterisk -rx fax show stats", (
            "Remote command must not be an unquoted string of bare words"
        )

    @pytest.mark.allow_subprocesses
    def test_remote_arg_is_single_element_not_multiple(self, monkeypatch):
        """The remote side must receive exactly one string argument (not 6)."""
        calls = []

        def _fake_run(argv, **_kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        SshTransport(host="pbx").asterisk("fax show stats")

        full = calls[0]
        # argv is: ['ssh', opts..., 'pbx', '<remote-cmd>']
        # the remote command is the last element; everything before it is ssh args
        # find the position of the host
        host_idx = full.index("pbx")
        # there must be exactly one element after the host
        assert len(full) - host_idx - 1 == 1, (
            f"Expected 1 remote arg after host, got {full[host_idx+1:]!r}"
        )


# ---------------------------------------------------------------------------
# 2. LocalTransport — sudo skip for asterisk user
# ---------------------------------------------------------------------------

class TestLocalTransportSudo:
    """LocalTransport must not add sudo -n when run as the asterisk user.

    Legacy reference: legacy/fax/fax/cli.py:62-64.
    """

    @pytest.mark.allow_subprocesses
    def test_no_sudo_when_asterisk_user(self, monkeypatch):
        calls = []

        def _fake_run(argv, **_kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, returncode=0, stdout="ok\n")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        t = LocalTransport(is_asterisk_user=lambda: True)
        t.asterisk("fax show stats")

        assert calls
        argv = calls[0]
        assert "sudo" not in argv, f"sudo must not appear for asterisk user, got {argv!r}"
        assert argv[0] == "asterisk"

    @pytest.mark.allow_subprocesses
    def test_sudo_when_not_asterisk_user(self, monkeypatch):
        calls = []

        def _fake_run(argv, **_kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, returncode=0, stdout="ok\n")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        t = LocalTransport(is_asterisk_user=lambda: False)
        t.asterisk("fax show stats")

        assert calls
        argv = calls[0]
        assert argv[:2] == ["sudo", "-n"], f"Expected sudo -n prefix, got {argv!r}"


# ---------------------------------------------------------------------------
# 3. Host from FAX_EXCHANGE_HOST
# ---------------------------------------------------------------------------

class TestHostFromEnv:
    """The PBX hostname must come from FAX_EXCHANGE_HOST (default 'pbx').

    Legacy reference: legacy/fax/fax/cli.py:24.
    """

    def test_default_host_is_pbx(self):
        # EXCHANGE is set at import time; its default is 'pbx'
        # (unless the env var is already set in the test environment)
        import os  # noqa: PLC0415
        if "FAX_EXCHANGE_HOST" not in os.environ:
            assert EXCHANGE == "pbx"

    @pytest.mark.allow_subprocesses
    def test_ssh_transport_uses_exchange_host(self, monkeypatch):
        """A default SshTransport takes its host from FAX_EXCHANGE_HOST (reviewer fix: this test
        used to pass the host explicitly, so it could not see the environment path)."""
        monkeypatch.setenv("FAX_EXCHANGE_HOST", "pbx2.example.com")

        calls = []

        def _fake_run(argv, **_kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", _fake_run)

        t = SshTransport()          # no explicit host: the environment must decide
        t.asterisk("fax show stats")

        assert calls
        full = calls[0]
        assert "pbx2.example.com" in full, (
            f"Expected 'pbx2.example.com' in ssh argv, got {full!r}"
        )

    def test_cli_picks_ssh_to_the_env_host(self, monkeypatch):
        """Off the PBX, the CLI's transport is ssh to FAX_EXCHANGE_HOST."""
        import faxcli.cli as cli_mod  # noqa: PLC0415
        monkeypatch.setenv("FAX_EXCHANGE_HOST", "pbx3.example.com")
        monkeypatch.setattr(cli_mod.socket, "gethostname", lambda: "workstation")
        t = cli_mod._make_transport(local=False)
        assert isinstance(t, SshTransport) and t.host == "pbx3.example.com"

    def test_cli_is_local_on_the_env_host(self, monkeypatch):
        import faxcli.cli as cli_mod  # noqa: PLC0415
        monkeypatch.setenv("FAX_EXCHANGE_HOST", "pbx3.example.com")
        monkeypatch.setattr(cli_mod.socket, "gethostname", lambda: "pbx3")
        assert isinstance(cli_mod._make_transport(local=False), LocalTransport)

    @pytest.mark.allow_subprocesses
    def test_spool_uses_exchange_host(self, monkeypatch, tmp_path):
        """SshTransport.spool() must use scp with the transport's host."""
        calls = []

        def _fake_run(argv, **_kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", _fake_run)

        tif = tmp_path / "test.tif"
        tif.write_bytes(b"fake")
        t = SshTransport(host="mypbx.example.com")
        t.spool(str(tif), "test.tif", "/var/spool/asterisk/fax/test.tif")

        # The first call must be scp with the right host
        assert calls
        scp_call = calls[0]
        assert scp_call[0] == "scp"
        dest = scp_call[-1]
        assert dest.startswith("mypbx.example.com:"), (
            f"scp destination should start with host, got {dest!r}"
        )


# ---------------------------------------------------------------------------
# 4a. TimeoutExpired becomes a failed Reading
# ---------------------------------------------------------------------------

class TestTimeoutExpired:
    """subprocess.TimeoutExpired must be caught and returned as Reading.failure."""

    @pytest.mark.allow_subprocesses
    def test_ssh_timeout_returns_failure(self, monkeypatch):
        def _raise_timeout(*_a, **_kw):
            raise subprocess.TimeoutExpired(cmd="ssh", timeout=60)

        monkeypatch.setattr(subprocess, "run", _raise_timeout)
        t = SshTransport(host="pbx")
        r = t.asterisk("fax show stats")
        assert not r.ok
        assert "timed out" in r.why

    @pytest.mark.allow_subprocesses
    def test_local_timeout_returns_failure(self, monkeypatch):
        def _raise_timeout(*_a, **_kw):
            raise subprocess.TimeoutExpired(cmd="asterisk", timeout=60)

        monkeypatch.setattr(subprocess, "run", _raise_timeout)
        t = LocalTransport(is_asterisk_user=lambda: False)
        r = t.asterisk("fax show stats")
        assert not r.ok
        assert "timed out" in r.why


# ---------------------------------------------------------------------------
# 4b. send --dry-run under ReplayTransport
# ---------------------------------------------------------------------------

class TestSendDryRunReplay:
    """send --dry-run under ReplayTransport must write the TIFF into the
    test's spool_dir and emit the legacy dry-run JSON shape.
    """

    def test_dry_run_writes_tiff_into_spool_dir(self, tmp_path):
        from faxcli.cli import main  # noqa: PLC0415

        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        buf = io.StringIO()
        rc = main(
            ["--json", "send", str(pdf), "12025550142", "--dry-run"],
            transport=ReplayTransport(spool_dir=tmp_path),
            stdout=buf,
        )
        assert rc == 0
        tifs = list(tmp_path.glob("*.tif"))
        assert tifs, "ReplayTransport.render() must write a .tif into spool_dir"

    def test_dry_run_json_shape(self, tmp_path):
        """The JSON output must contain ok, dry_run, number, pages, tif."""
        from faxcli.cli import main  # noqa: PLC0415

        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        buf = io.StringIO()
        rc = main(
            ["--json", "send", str(pdf), "12025550142", "--dry-run"],
            transport=ReplayTransport(spool_dir=tmp_path),
            stdout=buf,
        )
        assert rc == 0
        obj = json.loads(buf.getvalue())
        assert obj["ok"] is True
        assert obj["dry_run"] is True
        assert obj["number"] == "12025550142"
        assert obj["pages"] == 1
        assert "tif" in obj

    def test_dry_run_tif_is_in_spool_dir(self, tmp_path):
        """The 'tif' field in the JSON must point into the spool_dir."""
        from faxcli.cli import main  # noqa: PLC0415

        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        buf = io.StringIO()
        main(
            ["--json", "send", str(pdf), "12025550142", "--dry-run"],
            transport=ReplayTransport(spool_dir=tmp_path),
            stdout=buf,
        )
        obj = json.loads(buf.getvalue())
        assert Path(obj["tif"]).parent == tmp_path, (
            f"tif should be in {tmp_path}, got {obj['tif']!r}"
        )
