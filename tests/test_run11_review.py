"""tests/test_run11_review.py — tests for the run-11 review fixes.

Covers:
  3. server.py: socket timeout on the handler; pool.submit RuntimeError releases permit.
  4. __main__.py: build() returns args; FaxServer that raises still runs cleanup.
  5. Replay spool alignment: ReplayTransport.spool_dir and Config.spool name the same dir.
  6. faxcli: TRUNK defined once (in api.py); phone_numbers.py is importable.
"""
from __future__ import annotations

import os
import socket
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from faxcli.transport import ReplayTransport
from faxconsole.routes import Config

FIXTURE_DIR = Path("tests/fixtures")


def _replay_config(tmp_path) -> Config:
    spool = str(tmp_path / "spool")
    os.makedirs(spool, exist_ok=True)
    t = ReplayTransport(
        fixture_dir=FIXTURE_DIR / "asterisk",
        cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
        spool_dir=spool,
    )
    return Config(transport=t, inbox=str(tmp_path / "inbox"), spool=spool, replay=True)


# ---------------------------------------------------------------------------
# Item 3 — socket timeout on handler
# ---------------------------------------------------------------------------

class TestHandlerSocketTimeout:
    """_PooledHTTPServer._run must set a socket timeout before dispatching."""

    def test_socket_timeout_is_set(self, tmp_path):
        """The timeout must be set on the socket before finish_request is called."""
        from faxconsole.server import FaxServer

        cfg = _replay_config(tmp_path)
        srv = FaxServer(cfg, pool_size=1, backlog=0, bind=False)
        try:
            seen_timeouts: list[float | None] = []

            server_sock, client_sock = socket.socketpair(socket.AF_UNIX)
            client_sock.sendall(b"GET /api/version HTTP/1.0\r\nHost: t\r\n\r\n")

            original_finish = type(srv._httpd).finish_request

            def _capture_timeout(self, request, client_address):
                seen_timeouts.append(request.gettimeout())
                return original_finish(self, request, client_address)

            with patch.object(type(srv._httpd), "finish_request", _capture_timeout):
                srv._httpd.process_request(server_sock, ("socketpair", 0))
                # Wait for the worker to finish
                done = threading.Event()
                srv._pool.submit(done.set)
                done.wait(timeout=5)

            client_sock.close()
            assert len(seen_timeouts) == 1
            assert seen_timeouts[0] == 30.0, (
                f"expected timeout=30.0, got {seen_timeouts[0]!r}"
            )
        finally:
            srv.close()

    def test_pool_submit_raises_releases_permit(self, tmp_path):
        """If pool.submit raises RuntimeError the semaphore permit is released."""
        from faxconsole.server import FaxServer

        cfg = _replay_config(tmp_path)
        srv = FaxServer(cfg, pool_size=1, backlog=0, bind=False)
        # Shut down the pool so submit raises RuntimeError.
        srv._pool.shutdown(wait=True)

        server_sock, client_sock = socket.socketpair(socket.AF_UNIX)
        client_sock.sendall(b"GET /api/version HTTP/1.0\r\nHost: t\r\n\r\n")

        try:
            srv._httpd.process_request(server_sock, ("socketpair", 0))
            # The RuntimeError path should have released the permit.
            permit_available = srv._sem.acquire(blocking=True, timeout=2)
            assert permit_available, "permit was not released after pool.submit raised"
            srv._sem.release()
        finally:
            client_sock.close()
            srv._httpd.server_close()


# ---------------------------------------------------------------------------
# Item 4 — build() returns args; FaxServer raising in try still runs cleanup
# ---------------------------------------------------------------------------

class TestMainBuild:
    def test_build_returns_three_tuple(self, tmp_path):
        """build() must return (config, cleanup, args)."""
        from faxconsole.__main__ import build

        result = build(["--replay", str(FIXTURE_DIR)])
        assert len(result) == 3, "build() must return (config, cleanup, args)"
        config, cleanup, args = result
        assert hasattr(args, "host")
        assert hasattr(args, "port")
        cleanup()

    def test_build_args_has_host_and_port(self, tmp_path):
        """build() must return the parsed namespace with host and port."""
        from faxconsole.__main__ import build

        _, cleanup, args = build(["--replay", str(FIXTURE_DIR), "--port", "9999",
                                  "--host", "0.0.0.0"])
        try:
            assert args.port == 9999
            assert args.host == "0.0.0.0"
        finally:
            cleanup()

    def test_fax_server_raise_still_runs_cleanup(self, tmp_path):
        """If FaxServer.__init__ raises, main()'s finally must still call cleanup()."""
        from unittest.mock import patch

        from faxconsole.__main__ import build

        cfg, cleanup, args = build(["--replay", str(FIXTURE_DIR)])
        cleaned_up = threading.Event()
        original_cleanup = cleanup

        def _watched_cleanup():
            cleaned_up.set()
            original_cleanup()

        # Simulate FaxServer.__init__ raising by importing and patching it.
        from faxconsole import __main__ as main_mod

        def _raising_server(*a, **kw):
            raise OSError("bind failed (test-injected)")

        original_build = main_mod.build

        def _build_patched(argv=None):
            c, _, a = original_build(argv)
            return c, _watched_cleanup, a

        with patch.object(main_mod, "FaxServer", _raising_server), \
             patch.object(main_mod, "build", _build_patched), pytest.raises(OSError, match="bind failed"):
            main_mod.main(["--replay", str(FIXTURE_DIR)])

        assert cleaned_up.is_set(), "cleanup() was not called when FaxServer raised"


# ---------------------------------------------------------------------------
# Item 5 — Replay spool alignment
# ---------------------------------------------------------------------------

class TestReplaySpoolAlignment:
    def test_spool_dir_and_config_spool_agree(self, tmp_path):
        """ReplayTransport.spool_dir and Config.spool must be the same directory."""
        spool = str(tmp_path / "spool")
        os.makedirs(spool, exist_ok=True)
        t = ReplayTransport(
            fixture_dir=FIXTURE_DIR / "asterisk",
            cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
            spool_dir=spool,
        )
        cfg = Config(transport=t, inbox=str(tmp_path / "inbox"), spool=spool, replay=True)
        assert str(t._spool_dir) == cfg.spool, (
            f"ReplayTransport._spool_dir={t._spool_dir!r} != Config.spool={cfg.spool!r}"
        )

    def test_tif_lands_in_config_spool(self, tmp_path):
        """A replay send must write the TIFF into the directory named by Config.spool."""
        import json as _json

        from faxconsole.routes import handle as _handle

        cfg = _replay_config(tmp_path)
        spool = cfg.spool

        boundary = "SPLbnd"
        pdf_data = b"%PDF-1.4\n%spool-align-test\n"
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
                + pdf_data + f'\r\n--{boundary}--\r\n'.encode())
        ctype = f"multipart/form-data; boundary={boundary}"
        cfg2_kwargs = {f.name: getattr(cfg, f.name) for f in cfg.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        cfg2_kwargs["write_token"] = "test-spool-align-token"

        from dataclasses import fields as _dc_fields
        vals = {f.name: getattr(cfg, f.name) for f in _dc_fields(cfg)}
        vals["write_token"] = "test-spool-align-token"
        cfg2 = Config(**vals)

        resp = _handle(
            "POST", "/api/fax/send",
            {"content-type": ctype, "content-length": str(len(body)),
             "x-auth-token": "test-spool-align-token"},
            body, cfg2,
        )
        obj = _json.loads(resp.body)
        assert obj.get("ok") is True, f"send failed: {obj}"
        # The tif value is masked as "replay:..." but the actual file is in spool.
        tifs = list(Path(spool).glob("*.tif"))
        assert len(tifs) == 1, f"expected 1 TIF in spool dir, found {tifs}"


# ---------------------------------------------------------------------------
# Item 6 — TRUNK defined once; phone_numbers importable
# ---------------------------------------------------------------------------

class TestTrunkDefinedOnce:
    def test_trunk_is_defined_in_api(self):
        from faxcli.api import TRUNK
        assert TRUNK == "voipms-fax"

    def test_trunk_is_one_definition(self):
        """Review of run 11: faxcli/cdr.py also defined TRUNK, so there were still two."""
        import faxcli.api as api
        import faxcli.cdr as cdr
        assert api.TRUNK is cdr.TRUNK
        sources = [p.read_text() for p in __import__("pathlib").Path("faxcli").glob("*.py")]
        assert sum(s.count('TRUNK = "voipms-fax"') for s in sources) == 1

    def test_cli_does_not_define_trunk(self):
        """cli.py must not define TRUNK itself — it was the duplicate."""
        import faxcli.cli as _cli
        # TRUNK should not be in the cli module's own namespace
        # (it may still be importable via api if re-exported, but we check cli's __dict__)
        assert "TRUNK" not in vars(_cli), (
            "cli.py still defines TRUNK; it should import from api.py instead"
        )

    def test_phone_numbers_module_importable(self):
        from faxcli.phone_numbers import InvalidNumber, normalize
        assert normalize("2025550142") == "12025550142"
        with pytest.raises(InvalidNumber):
            normalize("not-a-number")

    def test_numbers_module_removed(self):
        """faxcli.numbers must no longer exist (removed to avoid stdlib shadowing)."""
        import importlib.util
        spec = importlib.util.find_spec("faxcli.numbers")
        assert spec is None, (
            "faxcli.numbers still exists; it should have been removed"
        )
