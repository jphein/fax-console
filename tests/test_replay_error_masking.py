"""Regression tests that pin M2: replay error text never carries a machine path (the review of PR 8).

The fixture dir sits OUTSIDE the replay root (the temp dir that build() makes), and it has no cdr/ and no
voipms/. So every read that fails names a real path unless the mask holds. Before these tests, removing
the CDR-error mask left the whole suite green (the Oracle's S-b).
"""
import json
import shutil
import socket
from pathlib import Path

import pytest

from faxconsole import server
from faxconsole.__main__ import build
from faxconsole.routes import handle

FIX = Path("tests/fixtures")
MARK = "zqx7"      # a fictional word in the fixture dir's name: it must never reach a response


@pytest.fixture
def replay(tmp_path):
    fx = tmp_path / f"{MARK} fixture dir"          # a space, as a real deploy path might have
    shutil.copytree(FIX / "asterisk", fx / "asterisk")
    config, cleanup, _args = build(["--replay", str(fx)])
    try:
        config.voipms._refresh_once()               # its fixture HTTP fails: no voipms/ dir
        yield config, fx
    finally:
        cleanup()


def _no_machine_path(text, *dirs):
    for d in dirs:
        assert str(d) not in text and str(d).lstrip("/") not in text, text[:300]
    assert "/tmp/" not in text and "/home/" not in text, text[:300]


def test_the_log_why_is_masked(replay):
    config, fx = replay
    body = handle("GET", "/api/fax/log", {}, b"", config).body.decode()
    assert json.loads(body).get("why"), body[:200]           # the CDR read failed, and says why
    _no_machine_path(body, fx, config.replay_root)


def test_the_fax_state_why_is_masked(replay):
    config, fx = replay
    body = handle("GET", "/api/fax", {}, b"", config).body.decode()
    assert json.loads(body).get("why"), body[:200]
    _no_machine_path(body, fx, config.replay_root)


def test_the_voipms_error_is_masked(replay):
    config, fx = replay
    body = handle("GET", "/api/voipms", {}, b"", config).body.decode()
    assert json.loads(body).get("error"), body[:200]
    _no_machine_path(body, fx, config.replay_root)


def test_the_adapters_500_is_masked(replay, monkeypatch):
    config, fx = replay

    def boom(*_a, **_k):
        raise RuntimeError(f"cannot open {fx}/cdr/Master.csv")

    monkeypatch.setattr(server, "handle", boom)
    srv = server.FaxServer(config, pool_size=1, backlog=0, bind=False)
    a, b = socket.socketpair(socket.AF_UNIX)
    b.settimeout(5)
    try:
        b.sendall(b"GET /api/fax HTTP/1.1\r\nHost: t\r\n\r\n")
        srv._httpd.process_request(a, ("socketpair", 0))
        data = b""
        while chunk := b.recv(65536):
            data += chunk
    finally:
        b.close()
        srv.close()
    assert data.startswith(b"HTTP/1.0 500 "), data[:80]
    _no_machine_path(data.decode(errors="replace"), fx, config.replay_root)


def test_a_dir_name_with_spaces_leaves_no_fragment(replay):
    """S-a: masking token by token stops at a space, and the rest of the dir name leaked."""
    config, _fx = replay
    for route in ("/api/fax/log", "/api/fax", "/api/voipms"):
        assert MARK not in handle("GET", route, {}, b"", config).body.decode(), route


def test_a_relative_fixture_dir_is_masked_too(tmp_path, monkeypatch):
    """A relative --replay reached error text as given, and the masker only knew the absolute form."""
    rel = f"{MARK} fixture dir"
    shutil.copytree(FIX / "asterisk", tmp_path / rel / "asterisk")    # before chdir: FIX is relative
    monkeypatch.chdir(tmp_path)
    config, cleanup, _args = build(["--replay", rel])
    try:
        config.voipms._refresh_once()
        for route in ("/api/fax/log", "/api/fax", "/api/voipms"):
            body = handle("GET", route, {}, b"", config).body.decode()
            assert MARK not in body, (route, body[:200])
    finally:
        cleanup()
