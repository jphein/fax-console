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
import socket
from pathlib import Path

import pytest

from faxcli.transport import ReplayTransport
from faxconsole.routes import Config, handle

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
]


def _make_config(tmp_path) -> Config:
    spool = str(tmp_path / "spool")
    os.makedirs(spool, exist_ok=True)
    transport = ReplayTransport(
        fixture_dir=FIXTURE_DIR / "asterisk",
        cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
        spool_dir=spool,
    )
    return Config(
        transport=transport,
        inbox=str(tmp_path / "inbox"),
        spool=spool,
        write_token=WRITE_TOKEN,
        replay=True,
    )


def _assert_clean(response_text: str, tmpdir: str, label: str) -> None:
    """Fail if *response_text* contains any forbidden runtime value."""
    # 1. Must not contain the temp-dir prefix
    if tmpdir in response_text:
        pytest.fail(f"{label}: temp dir {tmpdir!r} leaked into response")

    # 2. Must not contain any absolute path under /tmp, /home, or /etc
    # that is NOT an allowlisted CDR spool path (which is under /var/spool).
    for m in re.finditer(r'"(/(?:tmp|home|etc)/[^"]*)"', response_text):
        path_val = m.group(1)
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
        cfg = _make_config(tmp_path)
        tmpdir = str(tmp_path)
        for route in _ALL_GET_ROUTES:
            resp = handle("GET", route, {}, b"", cfg)
            body_text = resp.body.decode(errors="replace")
            _assert_clean(body_text, tmpdir, f"GET {route}")

    def test_dry_run_send_is_clean(self, tmp_path):
        cfg = _make_config(tmp_path)
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
        cfg = _make_config(tmp_path)
        resp = handle("GET", "/api/version", {}, b"", cfg)
        obj = json.loads(resp.body)
        assert obj["host"] == "replay", (
            f"expected host='replay' in replay mode, got {obj['host']!r}"
        )
        assert _FAKE_HOSTNAME not in obj["host"]

    def test_fax_state_spool_and_inbox_are_masked(self, tmp_path):
        """GET /api/fax must show replay:spool and replay:inbox, not the temp dir."""
        cfg = _make_config(tmp_path)
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
        cfg = _make_config(tmp_path)
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
