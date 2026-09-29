#!/usr/bin/env python3
"""After a run: did Bob's own log show the gateway lock holding? (drift-gems, 2026-09-29, #7)

  bob_lock_check.py LOG_DIR [--origin URL]

LOG_DIR is the run's saved Bob log directory (scripts/bob-sandbox.sh copies Bob's logs there when
the sandbox exits; Bob Shell writes JSON lines under shell/). Every line is parsed as JSON, and only
`module`, `msg` and `data.url` are read, so the order of the keys does not matter. The run passes
(exit 0) only if all three hold:
  - a PolicyService line says "Loaded 1 policy/policies from file: GatewayUrl", so Bob read the
    read-only /etc/bob/policy.json;
  - at least one Gateway "HTTP request" line exists, since a run with no requests is no evidence;
  - every Gateway "HTTP request" / "HTTP request complete" URL has exactly the pinned origin:
    scheme, host and port, with the host read after any user-info, so a URL like
    https://pinned@elsewhere/ counts as elsewhere.
Otherwise it exits 3. It prints counts and origins only, never a path, an id or any other value.

This is a regression check, not the boundary. Bob writes these logs itself, so a hostile Bob could
forge them. The boundary is the read-only policy file and the sandbox. What the check catches is the
lock silently going away: a Bob update that stops reading /etc/bob/policy.json, a bind that no longer
lands, or a gateway change that no one pinned.
Aurora's control runs (2026-09-29) showed the shapes. The planted address was contacted only when
the policy was absent, and every request went to the pinned origin when it was present.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

# Must equal BOB_GATEWAY in scripts/bob-sandbox.sh (tests/test_bob_lock_check.py checks it).
PINNED = "https://api.us-east.bob.ibm.com"
LOADED = "Loaded 1 policy/policies from file: GatewayUrl"
REQUESTS = ("HTTP request", "HTTP request complete")


def origin(url: str) -> str:
    """scheme://host[:port], lower-cased, with any user-info dropped; "?" if it cannot be read."""
    try:
        u = urlsplit(url)
        host, port = u.hostname, u.port
    except ValueError:
        return "?"
    scheme = u.scheme.lower()
    if not scheme or not host:
        return "?"
    if port == {"https": 443, "http": 80}.get(scheme):
        port = None                                  # an explicit default port is the same origin
    return f"{scheme}://{host.lower()}" + (f":{port}" if port is not None else "")


def check(log_dir: Path, pinned: str) -> tuple[bool, str]:
    files = sorted(p for p in log_dir.rglob("*.log") if p.is_file()) if log_dir.is_dir() else []
    loaded = requests = unreadable = 0
    origins: dict[str, int] = {}
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except ValueError:
                    unreadable += 1
                    continue
                if not isinstance(o, dict):
                    unreadable += 1
                    continue
                module, msg = o.get("module"), o.get("msg")
                if module == "PolicyService" and msg == LOADED:
                    loaded += 1
                elif module == "Gateway" and msg in REQUESTS:
                    data = o.get("data")
                    url = data.get("url") if isinstance(data, dict) else None
                    o_ = origin(url) if isinstance(url, str) else "?"
                    origins[o_] = origins.get(o_, 0) + 1
                    requests += msg == "HTTP request"
    off = sum(c for o_, c in origins.items() if o_ != pinned)
    ok = bool(files) and loaded >= 1 and requests >= 1 and off == 0
    shown = ", ".join(f"{o_} x{c}" for o_, c in sorted(origins.items())) or "none"
    reasons = (("no Bob log", not files), ("no policy-loaded line", loaded < 1),
               ("no requests", requests < 1), (f"{off} off-origin", off > 0))
    why = [] if ok else [w for w, bad in reasons if bad]
    return ok, (f"bob-lock: {'OK' if ok else 'FAILED (' + '; '.join(why) + ')'}: {len(files)} log file(s), "
                f"policy loaded x{loaded}, {requests} request(s); origins: {shown}"
                + (f"; {unreadable} line(s) not a JSON object" if unreadable else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="check a Bob run's own log for the gateway lock")
    ap.add_argument("log_dir", type=Path)
    ap.add_argument("--origin", default=PINNED)
    a = ap.parse_args(argv)
    ok, line = check(a.log_dir, origin(a.origin))
    print(line)
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
