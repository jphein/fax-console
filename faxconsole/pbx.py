"""faxconsole.pbx — PBX status readers.

Port of read_trunk (legacy e:1009–1021), read_calls (legacy e:1024–1104),
and read_sip_endpoints (legacy e:1108–1136).

Each function accepts a ``transport`` (faxcli.transport.Transport) and an
optional ``vty_fn`` (read_calls only).  They return dicts with the same
shape as the legacy functions so the old page keeps working.

The cellular-core instrument in read_calls is behind an optional injected
callable ``vty_fn(msc_vty, command) -> str`` that defaults to "not probed"
(returns None), preserving the legacy meaning of a failed Reading.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from faxcli.transport import Transport


def read_trunk(transport: Transport) -> dict[str, Any]:
    """Port of legacy read_trunk (e:1009–1021).

    Returns a dict with ok, src, and either the registration fields or why.
    A failed Reading is reported as ok=False (same meaning as legacy None).
    """
    src = "asterisk -rx 'pjsip show registrations'"
    reading = transport.asterisk("pjsip show registrations")
    if not reading.ok:
        return {"ok": False, "src": src, "why": "asterisk CLI not reachable"}
    txt = reading.text
    for line in txt.splitlines():
        m = re.match(
            r"\s*(\S+)/(\S+)\s+(\S+)\s+(Registered|Unregistered|Rejected)"
            r"\s*(\(exp\. (\d+)s\))?",
            line,
        )
        if m:
            return {
                "ok": True,
                "src": src,
                "name": m.group(1),
                "uri": m.group(2),
                "status": m.group(4),
                "expires": m.group(6),
                "raw": txt.strip(),
            }
    return {"ok": True, "src": src, "status": None, "raw": txt.strip(),
            "why": "no registration row in output"}


def read_calls(
    transport: Transport,
    vty_fn: Callable[[Any, str], str] | None = None,
) -> dict[str, Any]:
    """Port of legacy read_calls (e:1024–1104).

    The cellular-core instrument (vty(MSC_VTY, "show connection")) is behind
    ``vty_fn``.  When vty_fn is None the MSC instrument is "not probed"
    (ok=False, as if the call raised).
    """
    out: dict[str, Any] = {"instruments": [], "subscribers": {}}
    reading = transport.asterisk("core show channels")
    if not reading.ok:
        out["instruments"].append({
            "name": "Asterisk channels", "ok": False,
            "src": "asterisk -rx 'core show channels'",
            "why": "asterisk CLI not reachable",
        })
    else:
        txt = reading.text
        m = re.search(r"(\d+) active calls?", txt)
        p = re.search(r"(\d+) calls? processed", txt)
        out["instruments"].append({
            "name": "Asterisk channels", "ok": True,
            "src": "asterisk -rx 'core show channels'",
            "value": int(m.group(1)) if m else None,
            "note": f"{p.group(1)} calls processed since start" if p else None,
            "raw": txt.strip(),
        })

    if vty_fn is not None:
        try:
            t = vty_fn(None, "show connection")
            blocks = re.split(r"^\s*Connection #\d+:", t, flags=re.M)[1:]
            subs: dict[str, Any] = {}
            for b in blocks:
                msisdn = re.search(r"MSISDN-(\d+)", b)
                state = re.search(r"RAN connection state: (\S+)", b)
                tags = sorted(set(re.findall(r"Use count: \d+ \(([^)]*)\)", b)))
                if msisdn:
                    subs[msisdn.group(1)] = {
                        "state": state.group(1) if state else None,
                        "tags": tags, "in_call": "cc" in tags,
                    }
            inst: dict[str, Any] = {
                "name": "MSC connections", "ok": True,
                "src": "cell-core vty 4254: show connection",
                "raw": t.strip() or "(no output -- no connections)",
                "value": len(blocks),
            }
            if blocks:
                ncc = sum(1 for v in subs.values() if v["in_call"])
                inst["note"] = (
                    f"{ncc} of {len(blocks)} carrying call-control; the "
                    f"rest are signalling only (location update, SMS)"
                )
            out["subscribers"] = subs
            out["instruments"].append(inst)
        except Exception as e:
            out["instruments"].append({
                "name": "MSC connections", "ok": False,
                "src": "cell-core vty 4254: show connection",
                "why": str(e),
            })
    else:
        out["instruments"].append({
            "name": "MSC connections", "ok": False,
            "src": "cell-core vty 4254: show connection",
            "why": "not probed",
        })

    by = {i["name"]: i for i in out["instruments"]}
    a = by.get("Asterisk channels", {})
    mc = by.get("MSC connections", {})
    out["value"] = a.get("value") if a.get("ok") else None
    out["cellular"] = mc.get("value") if mc.get("ok") else None
    out["impossible"] = (
        out["value"] is not None
        and out["cellular"] is not None
        and out["cellular"] > out["value"]
    )
    return out


def read_sip_endpoints(transport: Transport) -> dict[str, Any]:
    """Port of legacy read_sip_endpoints (e:1108–1136)."""
    src = "asterisk -rx 'pjsip show endpoints'"
    reading = transport.asterisk("pjsip show endpoints")
    if not reading.ok:
        return {"ok": False, "src": src, "why": "asterisk CLI not reachable"}
    txt = reading.text
    rows: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in txt.splitlines():
        m = re.match(
            r"\s*Endpoint:\s+(\S+?)(?:/\S*)?\s+(\S+(?: \S+)*?)\s+(\d+) of",
            line,
        )
        if m:
            cur = {
                "ext": m.group(1),
                "state": m.group(2).strip(),
                "channels": int(m.group(3)),
                "contact": None,
            }
            rows.append(cur)
            continue
        m2 = re.match(r"\s*Contact:\s+\S+/(\S+)\s+\S+\s+(\S+)\s", line)
        if m2 and cur:
            cur["contact"] = {"uri": m2.group(1), "status": m2.group(2)}
    return {
        "ok": True,
        "src": src,
        "rows": [r for r in rows if r["ext"].isdigit()],
        "infra": [r for r in rows if not r["ext"].isdigit()],
    }
