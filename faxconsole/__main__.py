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
import sys
import tempfile

from faxcli.transport import LocalTransport, ReplayTransport, SshTransport
from faxconsole.routes import Config
from faxconsole.server import FaxServer


def main(argv: list[str] | None = None) -> int:
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

    replay_tmpdir: str | None = None

    if a.replay:
        from pathlib import Path  # noqa: PLC0415
        # Replay mode: use a single temp dir for both spool and inbox so no
        # real paths are touched.  Removed on shutdown.
        replay_tmpdir = tempfile.mkdtemp(prefix="faxconsole-replay-")
        transport = ReplayTransport(
            fixture_dir=Path(a.replay) / "asterisk",
            cdr_path=Path(a.replay) / "cdr" / "Master.csv",
            spool_dir=replay_tmpdir,
        )
        config = Config(
            transport=transport,
            inbox=os.path.join(replay_tmpdir, "inbox"),
            spool=os.path.join(replay_tmpdir, "spool"),
            replay=True,
        )
        replay = True
    elif a.local:
        transport = LocalTransport()
        config = Config(transport=transport, inbox=a.inbox, replay=False)
        replay = False
    else:
        transport = SshTransport(host=a.ssh)  # host=None → exchange_host()
        config = Config(transport=transport, inbox=a.inbox, replay=False)
        replay = False

    server = FaxServer(config, host=a.host, port=a.port)
    print(f"faxconsole listening on {a.host}:{a.port} "
          f"({'replay' if replay else 'live'})", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    finally:
        if replay_tmpdir:
            shutil.rmtree(replay_tmpdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
