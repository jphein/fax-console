"""The review of run 13: the independent review's findings on PR 8 that run 13 left open, or opened.

No process, no TCP: the server is driven over AF_UNIX socketpairs, and ssh/scp through a fake subprocess.run.
"""
import contextlib
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

from faxcli.api import SendError, send
from faxcli.cdr import parse_cdr
from faxcli.transport import ReplayTransport, SshTransport
from faxconsole.routes import Config
from faxconsole.server import FaxServer

FIX = Path("tests/fixtures")
TOKEN = "fake-token-demo"


def _server(tmp_path):
    t = ReplayTransport(fixture_dir=FIX / "asterisk", cdr_path=FIX / "cdr" / "Master.csv",
                        spool_dir=str(tmp_path))
    cfg = Config(transport=t, inbox=str(tmp_path / "inbox"), spool=str(tmp_path), replay=True,
                 write_token=TOKEN)
    return FaxServer(cfg, pool_size=1, backlog=0, bind=False)


def _exchange(srv, raw):
    """Stream *raw* from a sender thread, as a browser upload does, then read the answer once the server
    has closed. The handler's buffered header read takes up to io.DEFAULT_BUFFER_SIZE (128 KiB on Python
    3.14), so the body must be larger than that for any of it to be left unread at the close."""
    import threading  # noqa: PLC0415
    server_end, client_end = socket.socketpair(socket.AF_UNIX)
    client_end.settimeout(5)

    def send():
        with contextlib.suppress(OSError):        # the server may close before all of it is sent
            client_end.sendall(raw)

    sender = threading.Thread(target=send, daemon=True)
    try:
        sender.start()
        srv._httpd.process_request(server_end, ("socketpair", 0))
        assert srv._sem.acquire(timeout=5), "the handler never finished"   # answered and closed
        srv._sem.release()
        sender.join(timeout=5)
        data = b""
        while chunk := client_end.recv(65536):
            data += chunk
        return data
    finally:
        client_end.close()


class TestEarlyRejectReachesItsClient:
    """Run 13 answers 401 and 413 before reading the body (M1). Closing with that body unread made the
    kernel reset the connection, so a client that had already sent it saw a reset, not the answer."""

    BODY = b"x" * (768 * 1024)        # more than the 128 KiB buffered header read

    def test_401_reaches_a_client_that_already_sent_its_body(self, tmp_path):
        srv = _server(tmp_path)
        try:
            head = (b"POST /api/fax/send HTTP/1.1\r\nHost: t\r\n"
                    b"Content-Type: multipart/form-data; boundary=B\r\n"
                    b"Content-Length: %d\r\n\r\n" % len(self.BODY))
            assert _exchange(srv, head + self.BODY).startswith(b"HTTP/1.0 401 ")
        finally:
            srv.close()

    def test_413_reaches_a_client_that_already_sent_part_of_its_body(self, tmp_path):
        srv = _server(tmp_path)
        try:
            head = (b"POST /api/fax/send HTTP/1.1\r\nHost: t\r\nX-Auth-Token: " + TOKEN.encode() + b"\r\n"
                    b"Content-Type: multipart/form-data; boundary=B\r\nContent-Length: 999999999\r\n\r\n")
            assert _exchange(srv, head + self.BODY).startswith(b"HTTP/1.0 413 ")
        finally:
            srv.close()


@pytest.mark.allow_subprocesses
def test_scp_puts_a_double_dash_before_its_operands(monkeypatch, tmp_path):
    calls = []

    def fake_run(argv, **_kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    tif = tmp_path / "a.tif"
    tif.write_bytes(b"II*\x00")
    SshTransport(host="pbx7.example.net").spool(str(tif), "a.tif", "/var/spool/asterisk/fax/a.tif")
    scp = next(c for c in calls if c and c[0] == "scp")
    assert "--" in scp and all(not a.startswith("-") for a in scp[scp.index("--") + 1:]), scp


def test_replay_which_gs_is_the_recorded_fixture_or_unread(tmp_path):
    """Finding A's rule: the replay transport serves what was recorded, and never invents a success."""
    assert ReplayTransport(fixture_dir=FIX / "asterisk").which_gs().text == "/usr/bin/gs"
    assert not ReplayTransport(fixture_dir=tmp_path).which_gs().ok


def test_a_limit_of_zero_or_less_is_no_rows_whichever_transport_read_the_text():
    text = (FIX / "cdr" / "Master.csv").read_text()
    assert parse_cdr(text, 0) == [] and parse_cdr(text, -1) == []
    assert len(parse_cdr(text, 2)) == 2


def test_an_unreadable_pdf_is_a_typed_error(tmp_path):
    pdf = tmp_path / "locked.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    pdf.chmod(0)
    try:
        with pytest.raises(SendError, match="could not read the PDF"):
            send(str(pdf), "12025550142", dry_run=True, transport=ReplayTransport(spool_dir=str(tmp_path)),
                 local=False)
    finally:
        pdf.chmod(0o600)


def test_a_failed_mkdtemp_is_a_typed_error(tmp_path, monkeypatch):
    def full(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(tempfile, "mkdtemp", full)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(SendError, match="temp dir"):
        send(str(pdf), "12025550142", dry_run=True, transport=ReplayTransport(spool_dir=str(tmp_path)),
             local=False)
