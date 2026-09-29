"""faxconsole.version — realm-sigil /api/version contract.

Port of generate_name, version_dict and the word lists (legacy e:350–455).
The realm for this service is ``fax.realm.watch`` (design requirement).
"""
from __future__ import annotations

import os
import platform
import socket
import sys
import time
from datetime import datetime, timezone

APP_NAME = "fax.realm.watch"
APP_DESC = "Fax panel back end — send, receive, and status"
APP_REALM = "signal"
APP_REPO = "https://github.com/jphein/fax-console"

# Vendored from realm-sigil words/realms.json ("signal" realm)
# (legacy e:374–387)
SIGIL_ADJECTIVES = [
    "Amplified", "Beaconing", "Blinking", "Broadcast", "Broadcasting",
    "Channeled", "Channelled", "Decoded", "Echoing", "Encrypted", "Filtered",
    "Grounded", "Harmonic", "Humming", "Isolated", "Jittered", "Keyed",
    "Latched", "Looping", "Modulated", "Narrowed", "Oscillating", "Pulsed",
    "Pulsing", "Quantized", "Relayed", "Resonant", "Synced", "Syncing", "Tuned",
]
SIGIL_NOUNS = [
    "Antenna", "Beacon", "Broadcast", "Carrier", "Channel", "Diode", "Emitter",
    "Frequency", "Gate", "Harbor", "Harmonic", "Impulse", "Junction",
    "Keystone", "Lattice", "Lighthouse", "Link", "Modem", "Node", "Oscillator",
    "Packet", "Ping", "Pulsar", "Pulse", "Qubit", "Relay", "Semaphore",
    "Signal", "Telegraph", "Transponder",
]

_START_MONO = time.monotonic()
_START_ISO = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_name(hash_: str, realm: str = "signal") -> str:
    """Port of realm_sigil.generate_name — must agree with every other impl."""
    try:
        seed = int(hash_, 16) if hash_ != "dev" else 0
    except ValueError:
        seed = 0
    adj = SIGIL_ADJECTIVES[seed % len(SIGIL_ADJECTIVES)]
    noun = SIGIL_NOUNS[(seed >> 8) % len(SIGIL_NOUNS)]
    return f"{adj} {noun} · {hash_}"


def _build_info() -> dict:
    """Build metadata; falls back to 'dev' when git is unavailable.

    We do NOT call subprocess here — the import-time git call is the one
    pattern the conftest subprocess guard exists to catch.  Instead we read
    the build.json written by the deploy script; if absent, hash='dev'.
    """
    info: dict = {"hash": "dev", "branch": "unknown", "dirty": False, "built": "unknown"}
    build_file = os.environ.get("FAXCONSOLE_BUILD_FILE", "/etc/faxconsole/build.json")
    try:
        import json  # noqa: PLC0415
        with open(build_file) as fh:
            info.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return info


BUILD = _build_info()


def version_dict() -> dict:
    """The realm-sigil /api/version contract (legacy e:434–454)."""
    h = BUILD["hash"]
    return {
        "name": APP_NAME,
        "description": APP_DESC,
        "version": generate_name(h, APP_REALM),
        "hash": h,
        "branch": BUILD["branch"],
        "dirty": BUILD["dirty"],
        "built": BUILD["built"],
        "realm": APP_REALM,
        "repo": APP_REPO,
        "commit_url": f"{APP_REPO}/commit/{h}" if APP_REPO and h != "dev" else "",
        "started": _START_ISO,
        "uptime": int(time.monotonic() - _START_MONO),
        "runtime": f"python{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}",
        "os": f"{sys.platform}/{platform.machine()}",
        "host": socket.gethostname(),
        "pid": os.getpid(),
    }
