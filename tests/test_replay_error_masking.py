"""Regression tests that pin M2: replay error text never carries a machine path (the review of PR 8).

The fixture dir sits OUTSIDE the replay root (the temp dir that build() makes), and it has no cdr/ and no
voipms/. So every read that fails names a real path unless the mask holds. Before these tests, removing
the CDR-error mask left the whole suite green (the Oracle's S-b).

Each test checks two things. The fictional marker never appears, and the answer carries the EXACT masked
form ("replay:/cdr/Master.csv"). The marker sits AFTER the space in the dir name, so a mask that stops at
the space leaks it. And since the mask fails closed, a missing exact replacement shows as the constant
message, not as a leak. Only the exact form tells the two apart (the Oracle's delta on PR 11).
"""
import dataclasses
import json
import shutil
import socket
from pathlib import Path

import pytest

from faxconsole import server
from faxconsole.__main__ import build
from faxconsole.routes import REPLAY_ERROR_WITHHELD, _mask_error, handle

FIX = Path("tests/fixtures")
MARK = "zqx7"      # a fictional word in the fixture dir's name: it must never reach a response
ROUTES = ("/api/fax/log", "/api/fax", "/api/voipms")


def _replay_on(fixture_dir_name, tmp_path):
    fx = tmp_path / fixture_dir_name
    shutil.copytree(FIX / "asterisk", fx / "asterisk")
    config, cleanup, _args = build(["--replay", str(fx)])
    config.voipms._refresh_once()                   # its fixture HTTP fails: no voipms/ dir
    return config, fx, cleanup


@pytest.fixture
def replay(tmp_path):
    config, fx, cleanup = _replay_on(f"fixture dir {MARK}", tmp_path)   # a space, as a deploy path may have
    try:
        yield config, fx
    finally:
        cleanup()


def _no_machine_path(text, *dirs):
    for d in dirs:
        assert str(d) not in text and str(d).lstrip("/") not in text, text[:300]
    assert "/tmp/" not in text and "/home/" not in text and MARK not in text, text[:300]


def _get(config, route):
    return json.loads(handle("GET", route, {}, b"", config).body.decode())


def test_the_log_why_is_masked(replay):
    config, fx = replay
    why = _get(config, "/api/fax/log").get("why") or ""
    assert "replay:/cdr/Master.csv" in why, why             # the CDR read failed, and says where, exactly
    _no_machine_path(why, fx, config.replay_root)


def test_the_fax_state_why_is_masked(replay):
    config, fx = replay
    why = _get(config, "/api/fax").get("why") or ""
    assert "replay:/cdr/Master.csv" in why, why
    _no_machine_path(why, fx, config.replay_root)


def test_the_voipms_error_is_masked(replay):
    config, fx = replay
    error = _get(config, "/api/voipms").get("error") or ""
    assert "replay:/voipms" in error, error
    _no_machine_path(error, fx, config.replay_root)


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
    text = data.decode(errors="replace")
    assert "cannot open replay:/cdr/Master.csv" in text, text[-300:]
    _no_machine_path(text, fx, config.replay_root)


def test_a_dir_name_with_spaces_leaves_no_fragment(replay):
    """S-a: masking token by token stops at a space, and the rest of the dir name leaked."""
    config, _fx = replay
    for route in ROUTES:
        assert MARK not in handle("GET", route, {}, b"", config).body.decode(), route


def test_a_relative_fixture_dir_is_masked_too(tmp_path, monkeypatch):
    """A relative --replay reached error text as given, and the masker only knew the absolute form."""
    rel = f"fixture dir {MARK}"
    shutil.copytree(FIX / "asterisk", tmp_path / rel / "asterisk")    # before chdir: FIX is relative
    monkeypatch.chdir(tmp_path)
    config, cleanup, _args = build(["--replay", rel])
    try:
        config.voipms._refresh_once()
        for route in ROUTES:
            body = handle("GET", route, {}, b"", config).body.decode()
            assert MARK not in body, (route, body[:200])
        assert "replay:/cdr/Master.csv" in _get(config, "/api/fax/log").get("why", "")
    finally:
        cleanup()


@pytest.mark.parametrize("name", [
    f"b\\s dir {MARK}",                   # repr() doubles the backslash
    f"it's \"q\" {MARK}",                 # both quote kinds: repr() escapes the single quote
])
def test_a_repr_escaped_dir_is_replaced_exactly(tmp_path, name):
    """OSError and KeyError quote a file name with repr(). Its escaped form missed the exact replacement,
    and the leftover split at the space (the Oracle's delta on PR 11)."""
    config, fx, cleanup = _replay_on(name, tmp_path)
    try:
        for route in ROUTES:
            assert MARK not in handle("GET", route, {}, b"", config).body.decode(), route
        assert "replay:/cdr/Master.csv" in _get(config, "/api/fax/log").get("why", "")
        assert "replay:/voipms" in _get(config, "/api/voipms").get("error", "")
    finally:
        cleanup()


def test_a_sibling_of_a_known_dir_fails_closed(replay):
    """A known dir is replaced only at a path boundary: "<fx>-qv9" is another directory. With no boundary it
    became "replay:-qv9/x" (the Oracle's delta on PR 11). Now it names an unknown path, so it fails closed."""
    config, fx = replay
    assert _mask_error(config, f"cannot open {fx}-qv9/x") == REPLAY_ERROR_WITHHELD
    assert _mask_error(config, f"cannot open {config.replay_root}-qv9/y") == REPLAY_ERROR_WITHHELD
    # With no "/" after the sibling, only the boundary sees it: without one, "replay:-qv9" looked clean.
    assert _mask_error(config, f"cannot open {fx}-qv9") == REPLAY_ERROR_WITHHELD
    assert _mask_error(config, f"cannot open '{config.replay_root}-qv9'") == REPLAY_ERROR_WITHHELD


@pytest.mark.parametrize("text", [
    "fetch failed: https://example.net/qv9",
    "cannot open /srv/qv9/x",
    "cannot open path:/srv/qv9/x",        # glued to other text: the old fallback kept it
    "cannot open file:/srv/qv9",
])
def test_any_other_path_or_url_fails_closed(replay, text):
    config, _fx = replay
    assert _mask_error(config, text) == REPLAY_ERROR_WITHHELD


def test_an_error_without_a_path_passes_through(replay):
    config, _fx = replay
    assert _mask_error(config, "not a PDF") == "not a PDF"


def test_live_mode_is_unchanged(replay):
    config, fx = replay
    live = dataclasses.replace(config, replay=False)
    assert _mask_error(live, f"cannot open {fx}/x") == f"cannot open {fx}/x"
