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

import json
import os
import socket
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
        import os

        from faxcli.api import send

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
        import json

        from faxconsole.routes import handle

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
        # "not under /var" alone would pass for a write to any other real path
        assert tif.startswith(str(tmp_path) + os.sep), f"tif {tif!r} outside the replay dir"
        assert pdf_path.startswith(str(tmp_path) + os.sep), f"pdf {pdf_path!r} outside the replay dir"


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
        from faxcli.phone_numbers import InvalidNumber
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
        import argparse
        import io
        import json

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
    """The capacity check in process_request, driven over AF_UNIX socketpairs (no TCP).

    The server is built with bind=False and handed one end of a socketpair per request,
    as its accept loop would hand it a connection. A request whose bytes have not arrived
    yet holds a worker, which makes "the pool is busy" deterministic without sleeps.
    """

    GET = b"GET /api/version HTTP/1.1\r\nHost: t\r\n\r\n"

    def _server(self, tmp_path, pool_size=1, backlog=0):
        from faxconsole.server import FaxServer
        t = ReplayTransport(fixture_dir=FIXTURE_DIR / "asterisk",
                            cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
                            spool_dir=str(tmp_path))
        cfg = Config(transport=t, inbox=str(tmp_path / "inbox"), spool=str(tmp_path), replay=True)
        return FaxServer(cfg, pool_size=pool_size, backlog=backlog, bind=False)

    @staticmethod
    def _connect(srv, clients, send=b""):
        server_end, client_end = socket.socketpair(socket.AF_UNIX)
        client_end.settimeout(5)
        clients.append(client_end)
        if send:
            client_end.sendall(send)
        srv._httpd.process_request(server_end, ("socketpair", 0))
        return client_end

    @staticmethod
    def _read_all(sock):
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
        return data

    @staticmethod
    def _close(srv, clients):
        for c in clients:        # a worker blocked on a silent client sees EOF and returns
            c.close()
        srv.close()

    def test_request_over_capacity_gets_503_and_is_not_queued(self, tmp_path):
        srv, clients = self._server(tmp_path), []          # capacity 1: one worker, no backlog
        try:
            busy = self._connect(srv, clients)             # holds the only slot
            over = self._connect(srv, clients, self.GET)
            head, _, body = self._read_all(over).partition(b"\r\n\r\n")
            assert head.startswith(b"HTTP/1.0 503 ")
            assert b"\r\nRetry-After: " in head
            assert b"\r\nContent-Type: application/json" in head
            assert json.loads(body)["ok"] is False
            busy.sendall(self.GET)                         # the held request is still served
            assert self._read_all(busy).startswith(b"HTTP/1.0 200 ")
        finally:
            self._close(srv, clients)

    def test_backlog_queues_rather_than_refusing(self, tmp_path):
        srv, clients = self._server(tmp_path, pool_size=1, backlog=1), []
        try:
            busy = self._connect(srv, clients)             # the one worker
            queued = self._connect(srv, clients, self.GET) # the backlog slot: waits, is not refused
            third = self._connect(srv, clients, self.GET)  # over capacity
            assert self._read_all(third).startswith(b"HTTP/1.0 503 ")
            busy.sendall(self.GET)
            assert self._read_all(busy).startswith(b"HTTP/1.0 200 ")
            assert self._read_all(queued).startswith(b"HTTP/1.0 200 ")
        finally:
            self._close(srv, clients)

    def test_slot_is_released_after_each_request(self, tmp_path):
        srv, clients = self._server(tmp_path), []          # capacity 1
        try:
            for _ in range(3):
                c = self._connect(srv, clients, self.GET)
                assert self._read_all(c).startswith(b"HTTP/1.0 200 ")
                assert srv._sem.acquire(timeout=5), "the worker never released its slot"
                srv._sem.release()
        finally:
            self._close(srv, clients)

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
