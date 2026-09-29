"""faxcli.transport — the one I/O seam.

Defines the Reading result type, the Transport protocol, a LocalTransport,
an SshTransport, and a ReplayTransport for tests.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
SUDO = ["sudo", "-n"]

ASTERISK_FIXTURE_DIR = Path("tests/fixtures/asterisk")
CDR_FIXTURE_PATH = Path("tests/fixtures/cdr/Master.csv")


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
    def success(cls, text: str) -> "Reading":
        return cls(ok=True, text=text)

    @classmethod
    def failure(cls, why: str) -> "Reading":
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


class LocalTransport:
    """Runs Asterisk CLI commands locally (no SSH).

    Used when --local is set or the host is the PBX.
    """

    def asterisk(self, cmd: str) -> Reading:
        try:
            r = subprocess.run(
                SUDO + ["asterisk", "-rx", cmd],
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
            with open(_CDR_PATH, newline="") as f:
                return Reading.success(f.read())
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


class SshTransport:
    """Runs Asterisk CLI commands via SSH."""

    def __init__(self, host: str = "pbx"):
        self.host = host

    def _ssh(self, argv: list[str]) -> Reading:
        full = ["ssh"] + SSH_OPTS + [self.host, " ".join(argv)]
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


class ReplayTransport:
    """Serves recorded fixtures from the tests/fixtures/ directories.

    Command→file mapping: spaces in the Asterisk command become underscores,
    hyphens and other characters are kept.  Example:
      ``pjsip show endpoint voipms-fax`` → ``asterisk/pjsip_show_endpoint_voipms-fax.txt``

    Failures can be injected by passing a set of command strings to *fail_commands*.
    """

    def __init__(
        self,
        fixture_dir: Path | str | None = None,
        cdr_path: Path | str | None = None,
        fail_commands: set[str] | None = None,
        fail_cdr: bool = False,
        fail_gs: bool = False,
    ):
        self._ast_dir = Path(fixture_dir) if fixture_dir else ASTERISK_FIXTURE_DIR
        self._cdr_path = Path(cdr_path) if cdr_path else CDR_FIXTURE_PATH
        self._fail_cmds: set[str] = fail_commands or set()
        self._fail_cdr = fail_cdr
        self._fail_gs = fail_gs

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
