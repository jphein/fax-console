"""faxcli.transport — the one I/O seam.

Defines the Reading result type, the Transport protocol, a LocalTransport,
an SshTransport, and a ReplayTransport for tests.
"""
from __future__ import annotations

import collections
import contextlib
import os
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
SUDO = ["sudo", "-n"]

ASTERISK_FIXTURE_DIR = Path("tests/fixtures/asterisk")
CDR_FIXTURE_PATH = Path("tests/fixtures/cdr/Master.csv")

def exchange_host() -> str:
    """The PBX host name: FAX_EXCHANGE_HOST, default "pbx" (legacy/fax/fax/cli.py:24).

    Read when a transport is built, not at import, so a caller (or a test) that sets the
    variable later still gets it."""
    return os.environ.get("FAX_EXCHANGE_HOST", "pbx")


EXCHANGE = exchange_host()  # the import-time value, kept for existing callers


@dataclass(frozen=True)
class Reading:
    """Result of a single transport read.

    ok=True  means the command ran and text is its stdout (possibly empty).
    ok=False means the command could not run; why describes the error.
    """

    ok: bool
    text: str
    why: str = ""

    @classmethod
    def success(cls, text: str) -> Reading:
        return cls(ok=True, text=text)

    @classmethod
    def failure(cls, why: str) -> Reading:
        return cls(ok=False, text="", why=why)


class Transport(Protocol):
    """Minimal I/O seam used by the CLI commands."""

    def asterisk(self, cmd: str) -> Reading:
        """Run an Asterisk CLI command and return its stdout."""
        ...

    def read_cdr(self, limit: int) -> Reading:
        """Return the tail of Master.csv as text."""
        ...

    def which_gs(self) -> Reading:
        """Return the path of ghostscript if available, else failure."""
        ...

    def render(self, pdf: str, tif: str) -> Reading:
        """Convert a PDF to a TIFF via ghostscript. tif is the destination path."""
        ...

    def spool(self, localtif: str, name: str, spooled: str) -> Reading:
        """Copy localtif to the spool and install it at spooled."""
        ...

    def cleanup(self, localtif: str) -> None:
        """Remove a temporary local TIFF after spooling."""
        ...


def _default_is_asterisk_user() -> bool:
    """Return True if the effective user is 'asterisk' (legacy/fax/fax/cli.py:69-74)."""
    try:
        import pwd  # noqa: PLC0415
        return pwd.getpwuid(os.geteuid()).pw_name == "asterisk"
    except Exception:
        return False


class LocalTransport:
    """Runs Asterisk CLI commands locally (no SSH).

    Used when --local is set or the host is the PBX.
    The *is_asterisk_user* callable is injectable so tests do not depend on
    the real OS user (legacy/fax/fax/cli.py:62-74).
    """

    def __init__(
        self,
        is_asterisk_user: Callable[[], bool] = _default_is_asterisk_user,
    ) -> None:
        self._is_asterisk_user = is_asterisk_user

    def _sudo_prefix(self) -> list[str]:
        # asterisk.ctl is 755: the asterisk user needs no sudo;
        # other users do (legacy/fax/fax/cli.py:62-64).
        return [] if self._is_asterisk_user() else SUDO

    def asterisk(self, cmd: str) -> Reading:
        try:
            r = subprocess.run(
                self._sudo_prefix() + ["asterisk", "-rx", cmd],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if r.returncode == 0:
                return Reading.success(r.stdout)
            return Reading.failure(f"asterisk -rx {cmd!r} exited {r.returncode}")
        except subprocess.TimeoutExpired:
            return Reading.failure(f"asterisk -rx {cmd!r} timed out")
        except Exception as exc:
            return Reading.failure(str(exc))

    def read_cdr(self, limit: int) -> Reading:
        from faxcli.cdr import CDR as _CDR_PATH  # noqa: PLC0415

        try:
            if limit <= 0:                     # `tail -n 0`: nothing (lines[-0:] would be every line)
                return Reading.success("")
            with open(_CDR_PATH, newline="") as f:
                tail = collections.deque(f, maxlen=limit)   # the CDR only grows: keep the tail only
            return Reading.success("".join(tail))
        except OSError as exc:
            return Reading.failure(str(exc))

    def which_gs(self) -> Reading:
        try:
            r = subprocess.run(["which", "gs"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                return Reading.success(r.stdout.strip())
            return Reading.failure("gs not found")
        except subprocess.TimeoutExpired:
            return Reading.failure("which gs timed out")
        except Exception as exc:
            return Reading.failure(str(exc))

    def render(self, pdf: str, tif: str) -> Reading:
        try:
            subprocess.run(
                ["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=tiffg4", "-r204x196",
                 "-dFIXEDMEDIA", "-dPDFFitPage", "-sPAPERSIZE=letter",
                 f"-sOutputFile={tif}", pdf],
                check=True,
                timeout=120,
            )
            return Reading.success(tif)
        except subprocess.TimeoutExpired:
            return Reading.failure("gs timed out")
        except subprocess.CalledProcessError as exc:
            return Reading.failure(f"gs failed: {exc}")
        except Exception as exc:
            return Reading.failure(str(exc))

    def spool(self, localtif: str, name: str, spooled: str) -> Reading:
        # Local: TIFF is already in the spool dir, nothing to copy
        return Reading.success(spooled)

    def cleanup(self, localtif: str) -> None:
        # Local: TIFF stays at its destination; nothing to remove
        pass


class SshTransport:
    """Runs Asterisk CLI commands via SSH."""

    def __init__(self, host: str | None = None) -> None:
        self.host = host or exchange_host()

    def _ssh(self, argv: list[str]) -> Reading:
        # Quote every remote argument so the remote shell treats each as one
        # word (legacy/fax/fax/cli.py:55: shlex.quote).
        remote_cmd = " ".join(shlex.quote(a) for a in argv)
        # "--" separates ssh options from the host, so a host that starts with
        # "-" cannot be interpreted as an ssh option.
        full = ["ssh"] + SSH_OPTS + ["--", self.host, remote_cmd]
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                return Reading.success(r.stdout)
            return Reading.failure(f"ssh {self.host} exited {r.returncode}: {r.stderr.strip()}")
        except subprocess.TimeoutExpired:
            return Reading.failure(f"ssh {self.host} timed out")
        except Exception as exc:
            return Reading.failure(str(exc))

    def asterisk(self, cmd: str) -> Reading:
        return self._ssh(SUDO + ["asterisk", "-rx", cmd])

    def read_cdr(self, limit: int) -> Reading:
        from faxcli.cdr import CDR as _CDR_PATH  # noqa: PLC0415

        return self._ssh(SUDO + ["tail", "-n", str(limit), _CDR_PATH])

    def which_gs(self) -> Reading:
        return self._ssh(["which", "gs"])

    def render(self, pdf: str, tif: str) -> Reading:
        try:
            subprocess.run(
                ["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=tiffg4", "-r204x196",
                 "-dFIXEDMEDIA", "-dPDFFitPage", "-sPAPERSIZE=letter",
                 f"-sOutputFile={tif}", pdf],
                check=True,
                timeout=120,
            )
            return Reading.success(tif)
        except subprocess.TimeoutExpired:
            return Reading.failure("gs timed out")
        except subprocess.CalledProcessError as exc:
            return Reading.failure(f"gs failed: {exc}")
        except Exception as exc:
            return Reading.failure(str(exc))

    def spool(self, localtif: str, name: str, spooled: str) -> Reading:
        remote_tmp = f"/tmp/{name}"
        try:
            subprocess.run(
                ["scp", "-q", "-o", "BatchMode=yes", localtif, f"{self.host}:{remote_tmp}"],
                check=True, timeout=60,
            )
        except subprocess.TimeoutExpired:
            return Reading.failure("scp timed out")
        except subprocess.CalledProcessError as exc:
            return Reading.failure(f"scp failed: {exc}")
        except Exception as exc:
            return Reading.failure(str(exc))
        # Legacy ran the install with check=True (legacy/fax/fax/cli.py:115): a failed install
        # aborts the send, so a TIFF that never reached the spool is never dialled.
        installed = self._ssh(SUDO + ["install", "-o", "asterisk", "-g", "asterisk", "-m", "644",
                                      remote_tmp, spooled])
        self._ssh(["rm", "-f", remote_tmp])  # best effort, as legacy (check=False)
        if not installed.ok:
            return Reading.failure(f"install into the spool failed: {installed.why}")
        return Reading.success(spooled)

    def cleanup(self, localtif: str) -> None:
        with contextlib.suppress(OSError):
            os.unlink(localtif)


class ReplayTransport:
    """Serves recorded fixtures from the tests/fixtures/ directories.

    Command→file mapping: spaces in the Asterisk command become underscores,
    hyphens and other characters are kept.  Example:
      ``pjsip show endpoint voipms-fax`` → ``asterisk/pjsip_show_endpoint_voipms-fax.txt``

    Failures can be injected by passing a set of command strings to *fail_commands*.

    For send tests, *spool_dir* is the directory where render() writes the TIFF.
    """

    def __init__(
        self,
        fixture_dir: Path | str | None = None,
        cdr_path: Path | str | None = None,
        fail_commands: set[str] | None = None,
        fail_cdr: bool = False,
        fail_gs: bool = False,
        spool_dir: Path | str | None = None,
    ):
        self._ast_dir = Path(fixture_dir) if fixture_dir else ASTERISK_FIXTURE_DIR
        self._cdr_path = Path(cdr_path) if cdr_path else CDR_FIXTURE_PATH
        self._fail_cmds: set[str] = fail_commands or set()
        self._fail_cdr = fail_cdr
        self._fail_gs = fail_gs
        self._spool_dir = Path(spool_dir) if spool_dir else None

    def _cmd_to_filename(self, cmd: str) -> str:
        return cmd.replace(" ", "_") + ".txt"

    def asterisk(self, cmd: str) -> Reading:
        if cmd in self._fail_cmds:
            return Reading.failure(f"injected failure for {cmd!r}")
        fname = self._cmd_to_filename(cmd)
        path = self._ast_dir / fname
        try:
            return Reading.success(path.read_text())
        except OSError:
            return Reading.failure(f"fixture not found: {path}")

    def read_cdr(self, limit: int) -> Reading:
        if self._fail_cdr:
            return Reading.failure("injected CDR failure")
        try:
            return Reading.success(self._cdr_path.read_text())
        except OSError as exc:
            return Reading.failure(str(exc))

    def which_gs(self) -> Reading:
        if self._fail_gs:
            return Reading.failure("injected gs failure")
        return Reading.success("/usr/bin/gs")

    def render(self, pdf: str, tif: str) -> Reading:
        """Write a minimal 1-page TIFF.

        If *spool_dir* was given at construction time, the TIFF is written
        into that directory so tests do not need /var/spool/asterisk/fax/.
        Returns the actual path written.
        """
        import struct  # noqa: PLC0415
        magic = b"II"
        version = struct.pack("<H", 42)
        ifd_off = struct.pack("<I", 8)
        ifd = struct.pack("<H", 0) + struct.pack("<I", 0)
        dest = str(self._spool_dir / Path(tif).name) if self._spool_dir else tif
        try:
            with open(dest, "wb") as f:
                f.write(magic + version + ifd_off + ifd)
            return Reading.success(dest)
        except OSError as exc:
            return Reading.failure(str(exc))

    def spool(self, localtif: str, name: str, spooled: str) -> Reading:
        """In replay mode the TIFF stays where render() wrote it."""
        return Reading.success(localtif)

    def cleanup(self, localtif: str) -> None:
        """Nothing to clean up in replay mode."""
