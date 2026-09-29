"""tests/test_run13_item1.py — early POST gate (run-13 item 1).

Verifies that server.py's do_POST checks the write token and the declared
Content-Length *before* calling rfile.read(), matching legacy e:2953–2961.

Two scenarios driven over AF_UNIX socketpairs (no TCP):
  A. No token, large declared body → 401 without the body being read.
  B. Correct token, oversized declared body → 413 without the body being read.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest

from faxcli.transport import ReplayTransport
from faxconsole.routes import Config
from faxconsole.server import FaxServer

FIXTURE_DIR = Path("tests/fixtures")
WRITE_TOKEN = "test-run13-item1-token"


def _server(tmp_path: Path, write_token: str = WRITE_TOKEN) -> FaxServer:
    t = ReplayTransport(
        fixture_dir=FIXTURE_DIR / "asterisk",
        cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
        spool_dir=str(tmp_path / "spool"),
    )
    cfg = Config(
        transport=t,
        inbox=str(tmp_path / "inbox"),
        spool=str(tmp_path / "spool"),
        replay=True,
        write_token=write_token,
    )
    return FaxServer(cfg, pool_size=2, backlog=0, bind=False)


def _send_request_and_read(srv: FaxServer, raw_request: bytes) -> bytes:
    """Send *raw_request* to srv over a socketpair; return the full response."""
    server_end, client_end = socket.socketpair(socket.AF_UNIX)
    client_end.settimeout(10)
    client_end.sendall(raw_request)
    srv._httpd.process_request(server_end, ("socketpair", 0))
    data = b""
    try:
        while True:
            chunk = client_end.recv(65536)
            if not chunk:
                break
            data += chunk
    except OSError:
        pass
    client_end.close()
    return data


class TestEarlyPostGate:
    """do_POST must reject before reading when the token is absent or the body is too large."""

    def test_no_token_large_declared_body_gets_401(self, tmp_path):
        """POST with no token, Content-Length=50 MB, no body sent → 401 immediately.

        The server must respond without attempting to read 50 MB.
        """
        import os
        os.makedirs(str(tmp_path / "spool"), exist_ok=True)
        srv = _server(tmp_path)
        try:
            # Declare 50 MB but send no body at all.
            fifty_mb = 50 * 1024 * 1024
            request = (
                f"POST /api/fax/send HTTP/1.0\r\n"
                f"Host: t\r\n"
                f"Content-Type: multipart/form-data; boundary=B\r\n"
                f"Content-Length: {fifty_mb}\r\n"
                f"\r\n"
            ).encode()
            # The server must respond without waiting for 50 MB of body.
            # Use a thread so we can enforce a time limit.
            result: list[bytes] = []
            exc_holder: list[Exception] = []

            def _do():
                try:
                    result.append(_send_request_and_read(srv, request))
                except Exception as e:
                    exc_holder.append(e)

            t_thread = threading.Thread(target=_do, daemon=True)
            t_thread.start()
            t_thread.join(timeout=5)
            assert not t_thread.is_alive(), "server blocked waiting for the body"
            assert not exc_holder, f"error in thread: {exc_holder}"
            assert result, "no response received"
            response = result[0]
            head = response.split(b"\r\n\r\n", 1)[0]
            assert head.startswith(b"HTTP/1.0 401 "), (
                f"expected 401, got: {head[:60]!r}"
            )
            body_bytes = response.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in response else b""
            obj = json.loads(body_bytes)
            assert obj["ok"] is False
        finally:
            srv.close()

    def test_authorized_oversized_body_gets_413(self, tmp_path):
        """POST with correct token but Content-Length above cap → 413 without reading.

        The cap is max_bytes (15 MB) + 65536. We declare cap+1 to trip it.
        """
        import os
        os.makedirs(str(tmp_path / "spool"), exist_ok=True)
        srv = _server(tmp_path)
        try:
            from faxconsole.routes import FAX_MAX_BYTES
            oversized = FAX_MAX_BYTES + 65536 + 1
            request = (
                f"POST /api/fax/send HTTP/1.0\r\n"
                f"Host: t\r\n"
                f"X-Auth-Token: {WRITE_TOKEN}\r\n"
                f"Content-Type: multipart/form-data; boundary=B\r\n"
                f"Content-Length: {oversized}\r\n"
                f"\r\n"
            ).encode()

            result: list[bytes] = []
            exc_holder: list[Exception] = []

            def _do():
                try:
                    result.append(_send_request_and_read(srv, request))
                except Exception as e:
                    exc_holder.append(e)

            t_thread = threading.Thread(target=_do, daemon=True)
            t_thread.start()
            t_thread.join(timeout=5)
            assert not t_thread.is_alive(), "server blocked waiting for the body"
            assert not exc_holder, f"error in thread: {exc_holder}"
            assert result, "no response received"
            response = result[0]
            head = response.split(b"\r\n\r\n", 1)[0]
            assert head.startswith(b"HTTP/1.0 413 "), (
                f"expected 413, got: {head[:60]!r}"
            )
            body_bytes = response.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in response else b""
            obj = json.loads(body_bytes)
            assert obj["ok"] is False
        finally:
            srv.close()
