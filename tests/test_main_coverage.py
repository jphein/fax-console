"""tests/test_main_coverage.py — edge-path coverage for faxconsole.__main__.

Targets lines untouched by the existing suite:
  - build() --local branch (line 104-106): Config uses LocalTransport
  - build() --ssh branch (line 107-109): Config uses SshTransport
  - main() SIGTERM handler (line 125): raises SystemExit(0)
  - main() print + serve loop (lines 131-133, 136): mocked serve_forever exits immediately
"""
from __future__ import annotations

import signal

import pytest

from faxcli.transport import LocalTransport, SshTransport
from faxconsole.__main__ import build

# ---------------------------------------------------------------------------
# build() --local branch
# ---------------------------------------------------------------------------

class TestBuildLocal:
    def test_local_builds_local_transport(self, tmp_path):
        """--local must produce a Config backed by LocalTransport."""
        config, cleanup, a = build(["--local"])
        try:
            assert isinstance(config.transport, LocalTransport)
            assert config.replay is False
        finally:
            cleanup()

    def test_local_inbox_default(self, tmp_path):
        """--local without --inbox uses the default inbox path."""
        config, cleanup, a = build(["--local"])
        try:
            # Default inbox comes from STATE_DIRECTORY env or /var/lib/faxconsole/fax
            assert config.inbox.endswith("/fax")
        finally:
            cleanup()

    def test_local_custom_inbox(self, tmp_path):
        """--local --inbox DIR uses the given inbox path."""
        inbox = str(tmp_path / "inbox")
        config, cleanup, a = build(["--local", "--inbox", inbox])
        try:
            assert config.inbox == inbox
        finally:
            cleanup()


# ---------------------------------------------------------------------------
# build() --ssh branch
# ---------------------------------------------------------------------------

class TestBuildSsh:
    def test_ssh_builds_ssh_transport(self):
        """--ssh must produce a Config backed by SshTransport."""
        config, cleanup, a = build(["--ssh", "pbx.example.com"])
        try:
            assert isinstance(config.transport, SshTransport)
            assert config.transport.host == "pbx.example.com"
            assert config.replay is False
        finally:
            cleanup()

    def test_ssh_without_host_uses_exchange_host(self, monkeypatch):
        """--ssh without an explicit host must use FAX_EXCHANGE_HOST / default 'pbx'."""
        monkeypatch.setenv("FAX_EXCHANGE_HOST", "pbx.example.com")
        config, cleanup, a = build(["--ssh"])
        try:
            assert isinstance(config.transport, SshTransport)
            assert config.transport.host == "pbx.example.com"
        finally:
            cleanup()

    def test_ssh_custom_port(self):
        """--port must be reflected on the parsed args."""
        config, cleanup, a = build(["--ssh", "pbx.example.com", "--port", "9000"])
        try:
            assert a.port == 9000
        finally:
            cleanup()


# ---------------------------------------------------------------------------
# main() — SIGTERM handler, print, serve_forever, cleanup
# ---------------------------------------------------------------------------

def _replay_fixtures(tmp_path):
    """Build a minimal replay fixture directory under tmp_path."""
    replay_dir = tmp_path / "fixtures"
    replay_dir.mkdir()
    (replay_dir / "asterisk").mkdir()
    (replay_dir / "cdr").mkdir()
    (replay_dir / "cdr" / "Master.csv").write_text("")
    (replay_dir / "voipms").mkdir()
    return replay_dir


class TestMain:
    def test_sigterm_handler_raises_system_exit(self, monkeypatch, tmp_path):
        """The SIGTERM handler must raise SystemExit(0)."""
        from faxconsole import __main__ as _main_mod  # noqa: PLC0415

        # Capture the SIGTERM handler that main() installs
        installed_handlers = {}

        def _capture_signal(signum, handler):
            installed_handlers[signum] = handler

        monkeypatch.setattr(signal, "signal", _capture_signal)

        # serve_forever raises SystemExit so main() exits immediately
        class _FakeServer:
            def __init__(self, config, host, port):
                pass
            def serve_forever(self):
                raise SystemExit(0)

        monkeypatch.setattr(_main_mod, "FaxServer", _FakeServer)

        replay_dir = _replay_fixtures(tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            _main_mod.main(["--replay", str(replay_dir)])
        assert exc_info.value.code == 0

        # The SIGTERM handler must have been registered
        assert signal.SIGTERM in installed_handlers
        # Calling the handler must raise SystemExit(0)
        handler = installed_handlers[signal.SIGTERM]
        with pytest.raises(SystemExit) as exc2:
            handler(signal.SIGTERM, None)
        assert exc2.value.code == 0

    def test_main_cleanup_called_on_exit(self, monkeypatch, tmp_path):
        """cleanup() must be called even when serve_forever raises SystemExit."""
        from faxconsole import __main__ as _main_mod  # noqa: PLC0415

        cleanup_called = []

        original_build = _main_mod.build

        def _fake_build(argv=None, clock=None):
            config, cleanup, a = original_build(argv, clock)
            original_cleanup = cleanup

            def _tracking_cleanup():
                cleanup_called.append(True)
                original_cleanup()

            return config, _tracking_cleanup, a

        monkeypatch.setattr(_main_mod, "build", _fake_build)

        class _FakeServer:
            def __init__(self, config, host, port):
                pass
            def serve_forever(self):
                raise SystemExit(0)

        monkeypatch.setattr(_main_mod, "FaxServer", _FakeServer)
        monkeypatch.setattr(signal, "signal", lambda *a: None)

        replay_dir = _replay_fixtures(tmp_path)

        with pytest.raises(SystemExit):
            _main_mod.main(["--replay", str(replay_dir)])
        assert cleanup_called, "cleanup() was not called"

    def test_main_prints_listening_message(self, monkeypatch, tmp_path, capsys):
        """main() must print the listening address and mode to stderr."""
        from faxconsole import __main__ as _main_mod  # noqa: PLC0415

        class _FakeServer:
            def __init__(self, config, host, port):
                pass
            def serve_forever(self):
                raise SystemExit(0)

        monkeypatch.setattr(_main_mod, "FaxServer", _FakeServer)
        monkeypatch.setattr(signal, "signal", lambda *a: None)

        replay_dir = _replay_fixtures(tmp_path)

        with pytest.raises(SystemExit):
            _main_mod.main(["--replay", str(replay_dir)])
        captured = capsys.readouterr()
        assert "faxconsole" in captured.err
        assert "replay" in captured.err
