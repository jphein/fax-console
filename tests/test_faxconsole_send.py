"""tests/test_faxconsole_send.py — POST /api/fax/send gate tests and replay dry run.

Tests cover:
  - No token configured → 401
  - Wrong token → 401
  - confirm missing or wrong → 400
  - Oversize upload → 413
  - Not a PDF → 400
  - No file attached → 400
  - Bad number → 400
  - N11 number refused → 400
  - Replay mode → dry run (ok=True, dry_run=True, replay=True), writes only in tmpdir
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from faxcli.transport import ReplayTransport
from faxconsole.routes import Config, Response, handle

FIXTURE_DIR = Path("tests/fixtures")

# A minimal valid PDF header
_PDF_HEADER = b"%PDF-1.4\n%fake-pdf-for-tests\n"

WRITE_TOKEN = "test-secret-token-abc123"
# Fictional test number (202-555-0142 block)
FAX_NUMBER = "2025550142"
# N11 number: area code 211 is a blocked N11 code — 10-digit so normalizer adds '1'
N11_NUMBER = "2110100000"


def _transport(spool_dir=None, **kwargs) -> ReplayTransport:
    return ReplayTransport(
        fixture_dir=FIXTURE_DIR / "asterisk",
        cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
        spool_dir=spool_dir,
        **kwargs,
    )


def _config(inbox, spool_dir=None, token=WRITE_TOKEN, replay=False,
            max_bytes=15 * 1024 * 1024) -> Config:
    return Config(
        transport=_transport(spool_dir=spool_dir),
        inbox=str(inbox),
        spool="/var/spool/asterisk/fax",
        max_bytes=max_bytes,
        write_token=token,
        replay=replay,
    )


def _make_multipart(fields: dict, file_data: bytes | None = _PDF_HEADER,
                    filename: str = "doc.pdf") -> tuple[str, bytes]:
    """Build a minimal multipart/form-data body."""
    boundary = "TestBoundary1234"
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f'{value}\r\n'
        )
    if file_data is not None:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{filename}"\r\nContent-Type: application/pdf\r\n\r\n'
        )
        body = ("".join(parts)).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()
    else:
        body = ("".join(parts) + f"--{boundary}--\r\n").encode()
    content_type = f"multipart/form-data; boundary={boundary}"
    return content_type, body


def _post_send(headers: dict, body: bytes, cfg: Config) -> Response:
    return handle("POST", "/api/fax/send", headers, body, cfg)


# ---------------------------------------------------------------------------
# Write-gate refusals
# ---------------------------------------------------------------------------

class TestSendWriteGate:
    def test_no_token_configured_returns_401(self, tmp_path):
        cfg = _config(inbox=tmp_path / "inbox", token="")
        ctype, body = _make_multipart({"number": FAX_NUMBER, "confirm": "yes"})
        r = _post_send({"content-type": ctype, "content-length": str(len(body))}, body, cfg)
        assert r.status == 401
        obj = json.loads(r.body)
        assert obj["ok"] is False

    def test_wrong_token_returns_401(self, tmp_path):
        cfg = _config(inbox=tmp_path / "inbox")
        ctype, body = _make_multipart({"number": FAX_NUMBER, "confirm": "yes"})
        r = _post_send(
            {"content-type": ctype, "content-length": str(len(body)),
             "x-auth-token": "wrong-token"},
            body, cfg,
        )
        assert r.status == 401
        obj = json.loads(r.body)
        assert obj["ok"] is False

    def test_correct_token_does_not_refuse(self, tmp_path):
        """A correct token passes the gate (may still fail for other reasons)."""
        spool = tmp_path / "spool"
        spool.mkdir()
        cfg = _config(inbox=tmp_path / "inbox", spool_dir=spool, replay=True)
        ctype, body = _make_multipart({"number": FAX_NUMBER, "confirm": "yes"})
        r = _post_send(
            {"content-type": ctype, "content-length": str(len(body)),
             "x-auth-token": WRITE_TOKEN},
            body, cfg,
        )
        assert r.status != 401


# ---------------------------------------------------------------------------
# Pre-body validation
# ---------------------------------------------------------------------------

class TestSendPreBodyValidation:
    def test_oversize_content_length_returns_413(self, tmp_path):
        cfg = _config(inbox=tmp_path / "inbox", max_bytes=100)
        ctype, _ = _make_multipart({"number": FAX_NUMBER, "confirm": "yes"})
        big_body = b"x" * (100 + 65536 + 1)
        r = _post_send(
            {"content-type": ctype, "content-length": str(len(big_body)),
             "x-auth-token": WRITE_TOKEN},
            big_body, cfg,
        )
        assert r.status == 413

    def test_wrong_content_type_returns_400(self, tmp_path):
        cfg = _config(inbox=tmp_path / "inbox")
        body = b"hello"
        r = _post_send(
            {"content-type": "application/json", "content-length": str(len(body)),
             "x-auth-token": WRITE_TOKEN},
            body, cfg,
        )
        assert r.status == 400
        assert json.loads(r.body)["ok"] is False


# ---------------------------------------------------------------------------
# Field-level validation (correct auth + content-type)
# ---------------------------------------------------------------------------

class TestSendFieldValidation:
    def _send(self, fields: dict, file_data: bytes | None = _PDF_HEADER,
              tmp_path=None, filename: str = "doc.pdf") -> Response:
        inbox = tmp_path or tempfile.mkdtemp()
        cfg = _config(inbox=inbox)
        ctype, body = _make_multipart(fields, file_data=file_data, filename=filename)
        return _post_send(
            {"content-type": ctype, "content-length": str(len(body)),
             "x-auth-token": WRITE_TOKEN},
            body, cfg,
        )

    def test_confirm_missing_returns_400(self, tmp_path):
        r = self._send({"number": FAX_NUMBER}, tmp_path=tmp_path)
        assert r.status == 400
        assert "confirm" in json.loads(r.body)["detail"].lower()

    def test_confirm_wrong_value_returns_400(self, tmp_path):
        r = self._send({"number": FAX_NUMBER, "confirm": "no"}, tmp_path=tmp_path)
        assert r.status == 400

    def test_bad_number_returns_400(self, tmp_path):
        r = self._send({"number": "not-a-number", "confirm": "yes"}, tmp_path=tmp_path)
        assert r.status == 400
        obj = json.loads(r.body)
        assert obj["ok"] is False

    def test_n11_number_refused(self, tmp_path):
        """211 is a blocked N11 service code (10 digits → normalised to 12110100000)."""
        r = self._send({"number": N11_NUMBER, "confirm": "yes"}, tmp_path=tmp_path)
        assert r.status == 400

    def test_no_file_returns_400(self, tmp_path):
        r = self._send({"number": FAX_NUMBER, "confirm": "yes"},
                       file_data=None, tmp_path=tmp_path)
        assert r.status == 400
        detail = json.loads(r.body)["detail"].lower()
        assert "pdf" in detail or "file" in detail

    def test_not_pdf_returns_400(self, tmp_path):
        r = self._send({"number": FAX_NUMBER, "confirm": "yes"},
                       file_data=b"not-a-pdf", tmp_path=tmp_path)
        assert r.status == 400
        assert "PDF" in json.loads(r.body)["detail"]

    def test_oversize_pdf_returns_400(self, tmp_path):
        inbox = tmp_path
        cfg = _config(inbox=str(inbox), max_bytes=50)
        ctype, body = _make_multipart(
            {"number": FAX_NUMBER, "confirm": "yes"},
            file_data=b"%PDF-" + b"x" * 100,
        )
        r = _post_send(
            {"content-type": ctype, "content-length": str(len(body)),
             "x-auth-token": WRITE_TOKEN},
            body, cfg,
        )
        assert r.status == 400
        detail = json.loads(r.body)["detail"]
        assert "15 MB" in detail or "larger" in detail


# ---------------------------------------------------------------------------
# Replay dry run
# ---------------------------------------------------------------------------

class TestSendReplayDryRun:
    def _replay_send(self, tmp_path, fields=None):
        spool = tmp_path / "spool"
        spool.mkdir()
        inbox = tmp_path / "inbox"
        cfg = _config(inbox=inbox, spool_dir=spool, replay=True)
        f = {"number": FAX_NUMBER, "confirm": "yes"}
        if fields:
            f.update(fields)
        ctype, body = _make_multipart(f)
        return _post_send(
            {"content-type": ctype, "content-length": str(len(body)),
             "x-auth-token": WRITE_TOKEN},
            body, cfg,
        )

    def test_replay_returns_200(self, tmp_path):
        r = self._replay_send(tmp_path)
        assert r.status == 200

    def test_replay_response_has_ok_true(self, tmp_path):
        r = self._replay_send(tmp_path)
        assert json.loads(r.body)["ok"] is True

    def test_replay_response_has_replay_true(self, tmp_path):
        r = self._replay_send(tmp_path)
        assert json.loads(r.body).get("replay") is True

    def test_replay_response_has_dry_run_true(self, tmp_path):
        r = self._replay_send(tmp_path)
        assert json.loads(r.body).get("dry_run") is True

    def test_replay_detail_says_nothing_dialled(self, tmp_path):
        r = self._replay_send(tmp_path)
        detail = json.loads(r.body).get("detail", "")
        assert "dialled" in detail.lower() or "replay" in detail.lower()

    def test_replay_tif_stays_in_tmp(self, tmp_path):
        """TIF must be inside tmp_path, not in /var/spool."""
        r = self._replay_send(tmp_path)
        obj = json.loads(r.body)
        tif = obj.get("tif", "")
        assert str(tmp_path) in tif, f"tif {tif!r} should be inside {tmp_path}"
        assert "/var/spool" not in tif

    def test_replay_pdf_written_in_inbox(self, tmp_path):
        self._replay_send(tmp_path)
        inbox = tmp_path / "inbox"
        pdfs = list(inbox.glob("*.pdf"))
        assert len(pdfs) == 1

    def test_replay_pdf_not_in_var_spool(self, tmp_path):
        r = self._replay_send(tmp_path)
        obj = json.loads(r.body)
        pdf = obj.get("pdf", "")
        assert "/var/spool" not in pdf

    def test_replay_number_normalised(self, tmp_path):
        """10-digit input must be normalised to 11 digits in the response."""
        spool = tmp_path / "spool"
        spool.mkdir()
        inbox = tmp_path / "inbox"
        cfg = _config(inbox=inbox, spool_dir=spool, replay=True)
        ctype, body = _make_multipart({"number": FAX_NUMBER, "confirm": "yes"})
        r = _post_send(
            {"content-type": ctype, "content-length": str(len(body)),
             "x-auth-token": WRITE_TOKEN},
            body, cfg,
        )
        obj = json.loads(r.body)
        assert obj["ok"] is True
        assert obj["number"] == "1" + FAX_NUMBER
