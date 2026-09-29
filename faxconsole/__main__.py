"""faxconsole.__main__ — entry point for ``python3 -m faxconsole``.

Modes:
  --replay DIR   serve recorded fixtures via ReplayTransport
  --local        serve via LocalTransport (runs on the PBX)
  --ssh [HOST]   serve via SshTransport (default: FAX_EXCHANGE_HOST or 'pbx')

Default bind address: 127.0.0.1
Default port: 8093
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from faxcli.transport import LocalTransport, ReplayTransport, SshTransport
from faxconsole.routes import Config
from faxconsole.server import FaxServer
from faxconsole.voipms import VoipMsPoller, fixture_http


def build(
    argv: list[str] | None = None,
) -> tuple[Config, Callable[[], None], argparse.Namespace]:
    """Parse *argv*, wire up transports and pollers, and return ``(config, cleanup, args)``.

    ``cleanup()`` stops any background threads and removes any temp directories.
    In live modes it is a no-op.  ``main()`` calls it on shutdown, including on
    SIGTERM (systemd's default stop signal).

    Separating construction from serving lets tests call ``build()`` and then
    drive routes through the pure ``handle()`` function without binding a socket.
    """
    p = argparse.ArgumentParser(
        prog="python3 -m faxconsole",
        description="Fax panel HTTP service",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--replay", metavar="DIR", help="serve recorded fixtures from DIR")
    mode.add_argument("--local", action="store_true", help="run locally on the PBX")
    mode.add_argument("--ssh", metavar="HOST", nargs="?", const=None,
                      help="connect via SSH (default host: FAX_EXCHANGE_HOST or 'pbx')")
    p.add_argument("--port", type=int, default=8093, help="listen port (default: 8093)")
    p.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    p.add_argument("--inbox",
                   default=os.path.join(
                       os.environ.get("STATE_DIRECTORY", "/var/lib/faxconsole"), "fax"
                   ),
                   help="directory where uploaded PDFs are stored (ignored in replay mode)")
    a = p.parse_args(argv)

    cleanup_fns: list[Callable[[], None]] = []

    if a.replay:
        # Absolute from here on, so every error message carries the one string the masker replaces:
        # a relative --replay reached error text as given, and only absolute paths were masked.
        replay_dir = Path(os.path.abspath(a.replay))
        # Replay mode: use a single temp dir for both spool and inbox so no
        # real paths are touched.  Removed on cleanup.
        tmpdir = tempfile.mkdtemp(prefix="faxconsole-replay-")
        spool_dir = os.path.join(tmpdir, "spool")
        os.makedirs(spool_dir, exist_ok=True)

        # VoIP.ms poller backed by fixture JSON; creds not needed in replay mode.
        voipms_poller = VoipMsPoller(
            http=fixture_http(replay_dir / "voipms"),
            creds=lambda: ("fake-user@example.com", "fake-password-replay", ""),
            cache_path=os.path.join(tmpdir, "voipms.json"),
            legacy_cache=os.path.join(tmpdir, "voipms-legacy.json"),
        )
        voipms_poller.start()

        transport = ReplayTransport(
            fixture_dir=replay_dir / "asterisk",
            cdr_path=replay_dir / "cdr" / "Master.csv",
            spool_dir=spool_dir,
        )
        config = Config(
            transport=transport,
            inbox=os.path.join(tmpdir, "inbox"),
            spool=spool_dir,
            replay=True,
            voipms=voipms_poller,
            replay_root=tmpdir,
            replay_fixture_dir=str(replay_dir),   # the same string that every fixture path starts with
        )

        def _cleanup() -> None:
            voipms_poller.stop()
            shutil.rmtree(tmpdir, ignore_errors=True)

        cleanup_fns.append(_cleanup)

    elif a.local:
        transport = LocalTransport()
        config = Config(transport=transport, inbox=a.inbox, replay=False)
    else:
        transport = SshTransport(host=a.ssh)  # host=None → exchange_host()
        config = Config(transport=transport, inbox=a.inbox, replay=False)

    def cleanup() -> None:
        for fn in cleanup_fns:
            fn()

    return config, cleanup, a


def main(argv: list[str] | None = None) -> int:
    config, cleanup, a = build(argv)

    replay = a.replay is not None

    # SIGTERM → clean SystemExit so `finally` runs (systemd sends SIGTERM on stop).
    def _sigterm(_sig: int, _frame: object) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _sigterm)

    try:
        server = FaxServer(config, host=a.host, port=a.port)
        print(f"faxconsole listening on {a.host}:{a.port} "
              f"({'replay' if replay else 'live'})", file=sys.stderr, flush=True)
        server.serve_forever()
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
