"""tests/test_replay_surface.py — replay mode leaks no runtime paths or host identity.

Every GET route and one dry-run POST are checked: no response body may contain
  - the temp-dir prefix (e.g. /tmp/faxconsole-replay-XXXX)
  - the machine hostname
  - any absolute path under /tmp, /home, or /etc

Recorded fixture values that look like paths are explicitly allowlisted below,
each with a comment explaining why they are legitimate.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import tempfile
from pathlib import Path

import pytest

from faxcli.transport import ReplayTransport
from faxconsole.routes import Config, handle
from faxconsole.voipms import VoipMsPoller, fixture_http

FIXTURE_DIR = Path("tests/fixtures")
_PDF_HEADER = b"%PDF-1.4\n%replay-surface-test\n"
WRITE_TOKEN = "test-write-gate-token"

# ---------------------------------------------------------------------------
# Allowlisted values that are expected to appear in responses.
# Each entry is a regex pattern with a comment.
# ---------------------------------------------------------------------------

# Paths from the recorded CDR fixtures (tests/fixtures/cdr/Master.csv):
# these are historical spool paths from the PBX, not runtime-generated ones.
_CDR_SPOOL_PREFIX = re.compile(r"/var/spool/asterisk/fax/")

# TEST-NET IP addresses embedded in fixtures (192.0.2.x — RFC 5737 documentation range).
_TEST_NET = re.compile(r"\b192\.0\.2\.\d+\b")

# The fictional hostname injected by the monkeypatch — must NOT appear in responses.
_FAKE_HOSTNAME = "pbx7.example.net"

_ALL_GET_ROUTES = [
    "/api/fax/status",
    "/api/fax/log",
    "/api/fax",
    "/api/pbx/trunk",
    "/api/pbx/calls",
    "/api/pbx/endpoints",
    "/api/version",
    "/api/voipms",
]


def _make_config(tmp_path, *, voipms: bool = False) -> tuple["Config", "VoipMsPoller | None"]:
    spool = str(tmp_path / "spool")
    os.makedirs(spool, exist_ok=True)
    transport = ReplayTransport(
        fixture_dir=FIXTURE_DIR / "asterisk",
        cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
        spool_dir=spool,
    )
    poller: VoipMsPoller | None = None
    if voipms:
        poller = VoipMsPoller(
            http=fixture_http(FIXTURE_DIR / "voipms"),
            creds=lambda: ("fake@example.com", "fake-password-replay", ""),
            cache_path=str(tmp_path / "voipms.json"),
            legacy_cache=str(tmp_path / "voipms-legacy.json"),
        )
        poller.start()
    return Config(
        transport=transport,
        inbox=str(tmp_path / "inbox"),
        spool=spool,
        write_token=WRITE_TOKEN,
        replay=True,
        replay_root=str(tmp_path),
        voipms=poller,
    ), poller


def _assert_clean(response_text: str, tmpdir: str, label: str) -> None:
    """Fail if *response_text* contains any forbidden runtime value."""
    # 1. Must not contain the temp-dir prefix (anywhere in the response, not just as a JSON value)
    if tmpdir in response_text or tmpdir.lstrip("/") in response_text:   # with or without its first "/"
        pytest.fail(f"{label}: temp dir {tmpdir!r} leaked into response")

    # 2. Must not contain any absolute path under /tmp, /home, or /etc
    # that is NOT an allowlisted CDR spool path (which is under /var/spool).
    # Search anywhere in the string, not only when the path is a quoted JSON value.
    for m in re.finditer(r"(/(?:tmp|home|etc)/\S+)", response_text):
        path_val = m.group(1).rstrip("'\".,;)")   # trim trailing punctuation that is not part of the path
        # /var/spool/asterisk/fax/ paths come from recorded CDR fixtures — allowlisted.
        if not _CDR_SPOOL_PREFIX.match(path_val):
            pytest.fail(f"{label}: runtime path {path_val!r} leaked into response")

    # 3. Must not contain the (monkeypatched) machine hostname
    if _FAKE_HOSTNAME in response_text:
        pytest.fail(f"{label}: hostname {_FAKE_HOSTNAME!r} leaked into response")


class TestReplayPublicSurface:
    """No replay response may carry temp-dir paths, the hostname, or /tmp|/home|/etc paths."""

    @pytest.fixture(autouse=True)
    def _patch_hostname(self, monkeypatch):
        monkeypatch.setattr(socket, "gethostname", lambda: _FAKE_HOSTNAME)

    def test_all_get_routes_are_clean(self, tmp_path):
        cfg, _ = _make_config(tmp_path)
        tmpdir = str(tmp_path)
        for route in _ALL_GET_ROUTES:
            resp = handle("GET", route, {}, b"", cfg)
            body_text = resp.body.decode(errors="replace")
            _assert_clean(body_text, tmpdir, f"GET {route}")

    def test_dry_run_send_is_clean(self, tmp_path):
        cfg, _ = _make_config(tmp_path)
        tmpdir = str(tmp_path)
        boundary = "RSTbnd"
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
        body = (fields_part.encode() + file_part.encode()
                + _PDF_HEADER + f'\r\n--{boundary}--\r\n'.encode())
        ctype = f"multipart/form-data; boundary={boundary}"
        resp = handle(
            "POST", "/api/fax/send",
            {"content-type": ctype, "content-length": str(len(body)),
             "x-auth-token": WRITE_TOKEN},
            body, cfg,
        )
        obj = json.loads(resp.body)
        assert obj.get("ok") is True, f"send failed: {obj}"
        body_text = resp.body.decode(errors="replace")
        _assert_clean(body_text, tmpdir, "POST /api/fax/send dry-run")

    def test_version_host_is_replay_not_hostname(self, tmp_path):
        """In replay mode /api/version must return host='replay', not the real hostname."""
        cfg, _ = _make_config(tmp_path)
        resp = handle("GET", "/api/version", {}, b"", cfg)
        obj = json.loads(resp.body)
        assert obj["host"] == "replay", (
            f"expected host='replay' in replay mode, got {obj['host']!r}"
        )
        assert _FAKE_HOSTNAME not in obj["host"]

    def test_fax_state_spool_and_inbox_are_masked(self, tmp_path):
        """GET /api/fax must show replay:spool and replay:inbox, not the temp dir."""
        cfg, _ = _make_config(tmp_path)
        resp = handle("GET", "/api/fax", {}, b"", cfg)
        obj = json.loads(resp.body)
        assert obj["spool"] == "replay:spool", (
            f"spool should be masked, got {obj['spool']!r}"
        )
        assert obj["inbox"] == "replay:inbox", (
            f"inbox should be masked, got {obj['inbox']!r}"
        )

    def test_send_pdf_and_tif_are_masked(self, tmp_path):
        """POST /api/fax/send dry-run must return replay:… paths, not the real temp path."""
        cfg, _ = _make_config(tmp_path)
        tmpdir = str(tmp_path)
        boundary = "MKbnd"
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
        body = (fields_part.encode() + file_part.encode()
                + _PDF_HEADER + f'\r\n--{boundary}--\r\n'.encode())
        ctype = f"multipart/form-data; boundary={boundary}"
        resp = handle(
            "POST", "/api/fax/send",
            {"content-type": ctype, "content-length": str(len(body)),
             "x-auth-token": WRITE_TOKEN},
            body, cfg,
        )
        obj = json.loads(resp.body)
        assert obj.get("ok") is True, f"send failed: {obj}"
        for field in ("pdf", "tif"):
            val = obj.get(field, "")
            assert val.startswith("replay:"), (
                f"field {field!r} should start with 'replay:' in replay mode, got {val!r}"
            )
            assert tmpdir not in val, (
                f"field {field!r} must not contain the temp dir, got {val!r}"
            )


def test_send_is_clean_when_inbox_and_spool_share_no_root(tmp_path):
    """Review of run 11: masking by os.path.commonpath([inbox, spool]) strips only "/" when the two share
    no directory, and "replay:tmp/..." still named the whole temp dir. Config's own default spool
    (/var/spool/...) with an inbox under tmp_path is exactly that shape."""
    spool = str(tmp_path / "spool")
    os.makedirs(spool, exist_ok=True)
    transport = ReplayTransport(fixture_dir=FIXTURE_DIR / "asterisk",
                                cdr_path=FIXTURE_DIR / "cdr" / "Master.csv", spool_dir=spool)
    cfg = Config(transport=transport, inbox=str(tmp_path / "inbox"), write_token=WRITE_TOKEN, replay=True)
    boundary = "B1"
    pdf = b"%PDF-1.4\n%demo\n"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="number"\r\n\r\n2025550142\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="confirm"\r\n\r\nyes\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="doc.pdf"\r\n'
            f'Content-Type: application/pdf\r\n\r\n').encode() + pdf + f"\r\n--{boundary}--\r\n".encode()
    r = handle("POST", "/api/fax/send", {"content-type": f"multipart/form-data; boundary={boundary}",
               "content-length": str(len(body)), "x-auth-token": WRITE_TOKEN}, body, cfg)
    assert json.loads(r.body)["ok"] is True
    _assert_clean(r.body.decode(), str(tmp_path), "send (no shared root)")


# ---------------------------------------------------------------------------
# New tests for run-13 item 2: build()-based, voipms, send-after-spool-removed
# ---------------------------------------------------------------------------

class TestReplayWithBuild:
    """Use build(["--replay", ...]) to exercise the full wiring, including voipms poller,
    then check every GET route and a send-after-spool-removed for path leaks.
    """

    @pytest.fixture(autouse=True)
    def _patch_hostname(self, monkeypatch):
        monkeypatch.setattr(socket, "gethostname", lambda: _FAKE_HOSTNAME)

    def test_all_get_routes_clean_via_build(self):
        """build(['--replay', FIXTURE_DIR]) — every GET route must be path-clean.

        FIXTURE_DIR holds both asterisk/ and voipms/ sub-directories, so the voipms poller
        can serve real fixture data and its error field is exercised.
        """
        from faxconsole.__main__ import build

        config, cleanup, _args = build(["--replay", str(FIXTURE_DIR)])
        # The temp dir created by build() is the replay_root
        tmpdir = config.replay_root
        assert tmpdir, "build() must set replay_root"
        try:
            routes_to_check = _ALL_GET_ROUTES  # includes /api/voipms
            for route in routes_to_check:
                resp = handle("GET", route, {}, b"", config)
                body_text = resp.body.decode(errors="replace")
                _assert_clean(body_text, tmpdir, f"GET {route} (via build)")
        finally:
            cleanup()

    def test_send_after_spool_removed_is_path_clean(self, tmp_path):
        """A send made after the spool dir was removed must not leak paths in its error."""
        from faxconsole.__main__ import build

        config, cleanup, _args = build(["--replay", str(FIXTURE_DIR)])
        tmpdir = config.replay_root
        assert tmpdir
        try:
            # Remove the spool dir to force a render/write failure
            spool = config.spool
            shutil.rmtree(spool, ignore_errors=True)

            boundary = "SpoolGone"
            pdf_data = _PDF_HEADER
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="number"\r\n\r\n'
                f'2025550142\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="confirm"\r\n\r\n'
                f'yes\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="doc.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
            ).encode() + pdf_data + f'\r\n--{boundary}--\r\n'.encode()
            ctype = f"multipart/form-data; boundary={boundary}"

            # Need a write token; build() uses env or None — set it on the config
            from dataclasses import fields as _dc_fields
            vals = {f.name: getattr(config, f.name) for f in _dc_fields(config)}
            vals["write_token"] = WRITE_TOKEN
            from faxconsole.routes import Config as _Config
            cfg2 = _Config(**vals)

            resp = handle(
                "POST", "/api/fax/send",
                {"content-type": ctype,
                 "content-length": str(len(body)),
                 "x-auth-token": WRITE_TOKEN},
                body, cfg2,
            )
            body_text = resp.body.decode(errors="replace")
            # The send may succeed or fail (if the spool is gone it will fail),
            # but either way the response body must be path-clean.
            _assert_clean(body_text, tmpdir, "POST /api/fax/send after spool removed")
        finally:
            cleanup()

    def test_voipms_error_is_path_clean(self, tmp_path):
        """/api/voipms snapshot with a missing fixture raises an error that must be path-clean."""
        # Build a config whose voipms fixture dir does NOT exist, so the poller records an error.
        empty_dir = tmp_path / "empty-fixtures"
        empty_dir.mkdir()
        (empty_dir / "asterisk").mkdir()
        (empty_dir / "cdr").mkdir()
        # No voipms/ subdir, so the poller will fail to read fixtures and record an error.
        spool_dir = tmp_path / "spool"
        spool_dir.mkdir()
        transport = ReplayTransport(
            fixture_dir=empty_dir / "asterisk",
            cdr_path=empty_dir / "cdr" / "Master.csv",
            spool_dir=str(spool_dir),
        )
        voipms_dir = empty_dir / "voipms"
        # voipms_dir does not exist; the poller's http callable will raise KeyError with the path
        from faxconsole.voipms import VoipMsPoller, fixture_http
        poller = VoipMsPoller(
            http=fixture_http(voipms_dir),
            creds=lambda: ("fake@example.com", "fake-pass-replay", ""),
            cache_path=str(tmp_path / "voipms.json"),
            legacy_cache=str(tmp_path / "voipms-legacy.json"),
            # Force immediate poll by setting intervals to 0
            intervals={"balance": 0, "registration": 0, "did": 0},
        )
        # Trigger a poll to populate the error field
        poller._refresh_once()  # noqa: SLF001

        cfg = Config(
            transport=transport,
            inbox=str(tmp_path / "inbox"),
            spool=str(spool_dir),
            write_token=WRITE_TOKEN,
            replay=True,
            replay_root=str(tmp_path),
            voipms=poller,
        )
        resp = handle("GET", "/api/voipms", {}, b"", cfg)
        body_text = resp.body.decode(errors="replace")
        # The error field in the snapshot may contain a path; it must be masked.
        _assert_clean(body_text, str(tmp_path), "GET /api/voipms with error")
