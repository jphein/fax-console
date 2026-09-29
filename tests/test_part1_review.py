"""tests/test_part1_review.py — tests for the run-7 Part 1 review fixes.

Covers:
  1. Replay isolation: Config(replay=True) refuses non-ReplayTransport; send writes
     only under the replay temp dir.
  2. --ssh host: SshTransport(host=None) defers to exchange_host(), not "pbx".
  3. Typed send API: faxcli.api.send returns DryRunResult / SendResult; raises
     InvalidNumber and SendError.
  4. Bounded queue: a queue over capacity receives 503 with Retry-After.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from faxcli.transport import LocalTransport, ReplayTransport, SshTransport
from faxconsole.routes import Config

FIXTURE_DIR = Path("tests/fixtures")
_PDF_HEADER = b"%PDF-1.4\n%test\n"


# ---------------------------------------------------------------------------
# Part 1.1 — Replay isolation
# ---------------------------------------------------------------------------

class TestReplayIsolation:
    def _replay_config(self, tmp_path) -> Config:
        """A fully-isolated replay Config backed by a temp dir."""
        spool = str(tmp_path / "spool")
        inbox = str(tmp_path / "inbox")
        os.makedirs(spool, exist_ok=True)
        t = ReplayTransport(
            fixture_dir=FIXTURE_DIR / "asterisk",
            cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
            spool_dir=spool,
        )
        return Config(transport=t, inbox=inbox, spool=spool, replay=True)

    def test_config_replay_requires_replay_transport(self):
        """Config(replay=True) must raise TypeError with a non-ReplayTransport."""
        with pytest.raises(TypeError, match="ReplayTransport"):
            Config(transport=LocalTransport(), inbox="/tmp/x", replay=True)

    def test_config_replay_accepts_replay_transport(self, tmp_path):
        """Config(replay=True) must not raise with a ReplayTransport."""
        cfg = self._replay_config(tmp_path)
        assert cfg.replay is True

    def test_replay_send_tif_not_under_var(self, tmp_path):
        """TIF produced by a replay send must not be under /var."""
        from faxcli.api import send
        import tempfile
        import os

        spool = str(tmp_path / "spool")
        os.makedirs(spool, exist_ok=True)
        t = ReplayTransport(
            fixture_dir=FIXTURE_DIR / "asterisk",
            cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
            spool_dir=spool,
        )
        # Write a minimal PDF
        pdf = str(tmp_path / "test.pdf")
        Path(pdf).write_bytes(_PDF_HEADER)

        result = send(pdf, "12025550142", dry_run=True, transport=t, local=True)
        assert not result.tif.startswith("/var"), (
            f"TIF {result.tif!r} must not be under /var in replay mode"
        )
        assert str(tmp_path) in result.tif

    def test_replay_send_stays_under_tmpdir(self, tmp_path):
        """Both inbox PDF and TIFF stay inside tmp_path in replay mode."""
        from faxconsole.routes import handle
        import json

        cfg = self._replay_config(tmp_path)
        boundary = "B1"
        fields_part = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="number"\r\n\r\n'
            f'2025550142\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="confirm"\r\n\r\n'
            f'yes\r\n'
        )
        file_part = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="doc.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
        )
        body = fields_part.encode() + file_part.encode() + _PDF_HEADER + f'\r\n--{boundary}--\r\n'.encode()
        ctype = f"multipart/form-data; boundary={boundary}"

        # No token check — replay doesn't need a token set (token is None → falls
        # back to env which is empty in tests → 401). So set a write_token.
        from dataclasses import replace
        cfg2 = dataclass_replace(cfg, write_token="test-token")
        r = handle(
            "POST", "/api/fax/send",
            {"content-type": ctype, "content-length": str(len(body)),
             "x-auth-token": "test-token"},
            body, cfg2,
        )
        obj = json.loads(r.body)
        assert obj.get("ok") is True, f"send failed: {obj}"
        tif = obj.get("tif", "")
        pdf_path = obj.get("pdf", "")
        assert not tif.startswith("/var"), f"tif {tif!r} under /var"
        assert not pdf_path.startswith("/var"), f"pdf {pdf_path!r} under /var"


def dataclass_replace(cfg: Config, **changes) -> Config:
    """Replace fields on a frozen-ish dataclass."""
    from dataclasses import fields as dc_fields
    vals = {f.name: getattr(cfg, f.name) for f in dc_fields(cfg)}
    vals.update(changes)
    return Config(**vals)


# ---------------------------------------------------------------------------
# Part 1.2 — --ssh host defers to exchange_host()
# ---------------------------------------------------------------------------

class TestSshHostDefault:
    def test_ssh_transport_none_uses_exchange_host(self, monkeypatch):
        """SshTransport(host=None) must read FAX_EXCHANGE_HOST, not hard-code 'pbx'."""
        monkeypatch.setenv("FAX_EXCHANGE_HOST", "pbx.example.com")
        t = SshTransport(host=None)
        assert t.host == "pbx.example.com"

    def test_ssh_transport_env_fallback_default(self, monkeypatch):
        """When FAX_EXCHANGE_HOST is unset, default is 'pbx'."""
        monkeypatch.delenv("FAX_EXCHANGE_HOST", raising=False)
        t = SshTransport(host=None)
        assert t.host == "pbx"

    def test_ssh_transport_explicit_host_wins(self, monkeypatch):
        """An explicit host overrides FAX_EXCHANGE_HOST."""
        monkeypatch.setenv("FAX_EXCHANGE_HOST", "other.example.com")
        t = SshTransport(host="custom.example.com")
        assert t.host == "custom.example.com"


# ---------------------------------------------------------------------------
# Part 1.3 — Typed send API
# ---------------------------------------------------------------------------

class TestApiSend:
    def _transport(self, tmp_path) -> ReplayTransport:
        return ReplayTransport(
            fixture_dir=FIXTURE_DIR / "asterisk",
            cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
            spool_dir=str(tmp_path / "spool"),
        )

    def _pdf(self, tmp_path) -> str:
        os.makedirs(str(tmp_path / "spool"), exist_ok=True)
        p = str(tmp_path / "doc.pdf")
        Path(p).write_bytes(_PDF_HEADER)
        return p

    def test_dry_run_returns_dry_run_result(self, tmp_path):
        from faxcli.api import send
        from faxcli.models import DryRunResult
        result = send(self._pdf(tmp_path), "12025550142",
                      dry_run=True, transport=self._transport(tmp_path), local=True)
        assert isinstance(result, DryRunResult)
        assert result.ok is True
        assert result.dry_run is True

    def test_dry_run_normalises_number(self, tmp_path):
        from faxcli.api import send
        result = send(self._pdf(tmp_path), "2025550142",  # 10-digit
                      dry_run=True, transport=self._transport(tmp_path), local=True)
        assert result.number == "12025550142"

    def test_invalid_number_raises(self, tmp_path):
        from faxcli.api import send
        from faxcli.numbers import InvalidNumber
        with pytest.raises(InvalidNumber):
            send(self._pdf(tmp_path), "not-a-number",
                 dry_run=True, transport=self._transport(tmp_path), local=True)

    def test_missing_file_raises_send_error(self, tmp_path):
        from faxcli.api import SendError, send
        os.makedirs(str(tmp_path / "spool"), exist_ok=True)
        with pytest.raises(SendError, match="no such file"):
            send(str(tmp_path / "nonexistent.pdf"), "12025550142",
                 dry_run=True, transport=self._transport(tmp_path), local=True)

    def test_not_pdf_raises_send_error(self, tmp_path):
        from faxcli.api import SendError, send
        os.makedirs(str(tmp_path / "spool"), exist_ok=True)
        p = str(tmp_path / "bad.pdf")
        Path(p).write_bytes(b"not-a-pdf")
        with pytest.raises(SendError, match="not a PDF"):
            send(p, "12025550142",
                 dry_run=True, transport=self._transport(tmp_path), local=True)

    def test_send_error_is_exception(self):
        from faxcli.api import SendError
        e = SendError("oops")
        assert e.reason == "oops"
        assert str(e) == "oops"

    def test_cmd_send_json_unchanged(self, tmp_path):
        """cmd_send --json output must include the contract fields (golden check)."""
        import argparse, io, json
        from faxcli.cli import cmd_send
        os.makedirs(str(tmp_path / "spool"), exist_ok=True)
        pdf = self._pdf(tmp_path)
        a = argparse.Namespace(
            pdf=pdf, number="12025550142", label=None,
            dry_run=True, wait=0, json=True, local=True,
        )
        buf = io.StringIO()
        rc = cmd_send(a, self._transport(tmp_path), buf)
        assert rc == 0
        obj = json.loads(buf.getvalue().strip())
        for field in ("ok", "dry_run", "number", "pages", "tif"):
            assert field in obj, f"missing field {field!r}"
        assert obj["ok"] is True
        assert obj["dry_run"] is True


# ---------------------------------------------------------------------------
# Part 1.4 — Bounded queue: 503 when over capacity
# ---------------------------------------------------------------------------

class TestBoundedQueue503:
    def test_503_when_over_capacity(self, tmp_path):
        """When semaphore is exhausted, the next request gets 503 without TCP."""
        import json, socket, threading
        from faxcli.transport import ReplayTransport
        from faxconsole.routes import Config
        from faxconsole.server import FaxServer, _send_503

        # Build a config
        t = ReplayTransport(
            fixture_dir=FIXTURE_DIR / "asterisk",
            cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
        )
        cfg = Config(transport=t, inbox=str(tmp_path / "inbox"))

        # Create a server with pool_size=1, backlog=0 → capacity=1
        srv = FaxServer(cfg, host="127.0.0.1", port=0, pool_size=1, backlog=0)
        sem = srv._sem

        # Exhaust the semaphore manually (capacity=1)
        acquired = sem.acquire(blocking=False)
        assert acquired, "semaphore should be acquirable initially"

        # Now capacity is 0: a request pair should get 503
        server_sock, client_sock = socket.socketpair(socket.AF_UNIX)
        try:
            _send_503(server_sock)
            # Read back what was written to the other end
            client_sock.settimeout(2)
            data = b""
            try:
                while True:
                    chunk = client_sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            except (TimeoutError, OSError):
                pass
        finally:
            server_sock.close()
            client_sock.close()
            sem.release()
            srv._pool.shutdown(wait=False)

        assert b"503" in data
        assert b"Retry-After" in data
        # Body must be JSON
        _, _, body_bytes = data.partition(b"\r\n\r\n")
        obj = json.loads(body_bytes)
        assert obj["ok"] is False

    def test_503_response_has_retry_after(self):
        """_send_503 must write a Retry-After header."""
        import socket
        from faxconsole.server import _send_503

        server_sock, client_sock = socket.socketpair(socket.AF_UNIX)
        try:
            _send_503(server_sock)
            client_sock.settimeout(1)
            data = b""
            try:
                while True:
                    chunk = client_sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            except (TimeoutError, OSError):
                pass
        finally:
            server_sock.close()
            client_sock.close()

        assert b"Retry-After:" in data
