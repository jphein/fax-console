"""faxconsole.voipms — injectable VoIP.ms background poller.

Port of VoipMsPoller (legacy/console/telephony-console.py e:760–1003),
_voipms_scrub (e:681–712), and _voipms_creds (e:715–757).

Every legacy comment and design constraint is preserved:
  · credentials never reach an error string; error paths are scrubbed with
    ``from None``.
  · the credentials file is read line by line, keeping only three keys.
  · the cache is written atomically (os.replace).
  · None means "not measured", not zero.
  · snapshot() never blocks.
  · no API call happens on a request path.

I/O seams (all injectable for tests):
  · http(method, params) → dict     — replaces urllib.request
  · clock() → float                 — replaces time.time
  · sleep(secs)                     — replaces time.sleep (default: waits on stop event)
  · cache_path: str                 — replaces VOIPMS_CACHE_FILE
  · creds: callable or str          — replaces VOIPMS_ENV; callable → (user, pw, did);
                                       str → path passed to _creds()
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

# ---------------------------------------------------------------------------
# Module-level constants (mirror of legacy globals)
# ---------------------------------------------------------------------------

VOIPMS_API = "https://voip.ms/api/v1/rest.php"
VOIPMS_UA = "2g-telephony-console/1.0"
VOIPMS_SUBACCOUNT = "000000_house"
VOIPMS_INTERVALS: dict[str, int] = {"balance": 300, "registration": 300, "did": 3600}
VOIPMS_LOW_BALANCE: float = 5.00
VOIPMS_STALE_AFTER: int = 900

_DEFAULT_STATE_DIR = os.environ.get("STATE_DIRECTORY", "/var/lib/faxconsole")
_DEFAULT_CACHE = os.path.join(_DEFAULT_STATE_DIR, "voipms.json")
_DEFAULT_CREDS = "/etc/asterisk/sms-gateway.env"
# Legacy seed-only cache (exchange-status); read-only if our own cache is absent.
_LEGACY_CACHE = "/var/lib/exchange-status/voipms.json"

_PERSIST = (
    "balance", "spent_today", "calls_today", "time_today",
    "spent_total", "calls_total",
    "spent_today_measured", "calls_today_measured",
    "time_today_measured", "spent_total_measured", "calls_total_measured",
    "registered", "register_server", "register_ip", "register_next", "register_agent",
    "did_description", "did_sms_enabled", "did_e911", "did_next_billing", "did_routing",
    "fetched",
)


# ---------------------------------------------------------------------------
# _voipms_scrub (legacy e:681–712)
# ---------------------------------------------------------------------------

def _scrub(text: Any, *secrets: str) -> str:
    """Remove credentials from anything that could become an error string.

    ⛔ TWO MECHANISMS (legacy e:687–711):
      · replace the literal secret value — catches any path, including ones
        nobody anticipated, but misses a percent-encoded form;
      · rewrite ``api_password=...`` — catches the encoded form in a URL.
      Neither alone is sufficient; together they cover both escape routes.
    """
    out = str(text)
    for s in secrets:
        # ⛔ A DEGENERATE SECRET MAKES VALUE-REPLACEMENT DESTRUCTIVE (e:698–707).
        #   The length floor is not tuning: below it the mechanism is harmful.
        if s and len(s) >= 8:
            out = out.replace(s, "***")
            out = out.replace(urllib.parse.quote(s, safe=""), "***")
    # ⭐ ALWAYS, REGARDLESS OF THE ABOVE (e:708–711).
    out = re.sub(r"(api_password=)[^&\s\"']*", r"\1***", out)
    return out


# ---------------------------------------------------------------------------
# _voipms_creds (legacy e:715–757)
# ---------------------------------------------------------------------------

def _creds(creds_path: str) -> tuple[str, str, str]:
    """Exactly three keys out of the credential file.  Nothing else is retained.

    ⛔ THE WHOLE FILE IS NEVER HELD IN A VARIABLE (e:718–723): reads line by
    line, keeps the three it needs, discards every other line.
    """
    user = pw = did = None
    with open(creds_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            # ⛔ TOLERANCE, NOT AN ASSERTION (e:731–745): handle `export KEY=val`
            #   and quoted values so a common .env edit does not silently break auth.
            k = re.sub(r"^export\s+", "", k.strip())
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            if k == "VOIPMS_USER":
                user = v
            elif k == "VOIPMS_PASS":
                pw = v
            elif k == "VOIPMS_DID":
                did = v
            # every other line falls out of scope here, unread and unstored
    if not user or not pw:
        # ⛔ NAMES THE PATH AND THE MISSING KEY, NEVER A VALUE (e:754–756).
        raise KeyError(
            f"VOIPMS_USER and VOIPMS_PASS must both be set in {creds_path}"
        )
    return user, pw, (did or "")


# ---------------------------------------------------------------------------
# Default HTTP callable (real network; only for live mode)
# ---------------------------------------------------------------------------

def _live_http(method: str, params: dict[str, str]) -> dict:
    """Real VoIP.ms API call.  Never called in tests."""
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(VOIPMS_API + "?" + q,
                                  headers={"User-Agent": VOIPMS_UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


# ---------------------------------------------------------------------------
# fixture_http — replay helper
# ---------------------------------------------------------------------------

def fixture_http(fixture_dir: str | os.PathLike) -> Callable[[str, dict], dict]:
    """Return an http(method, params) callable that serves ``fixture_dir/<method>.json``.

    Raises ``KeyError`` for unknown methods; never touches the network.
    """
    from pathlib import Path  # noqa: PLC0415

    base = Path(fixture_dir)

    def _http(method: str, params: dict[str, str]) -> dict:  # noqa: ARG001
        path = base / f"{method}.json"
        if not path.exists():
            raise KeyError(f"fixture_http: no fixture for method {method!r} in {base}")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    return _http


# ---------------------------------------------------------------------------
# VoipMsPoller (legacy e:760–1003)
# ---------------------------------------------------------------------------

class VoipMsPoller:
    """Polls VoIP.ms in the background; the request path only reads snapshots.

    Ported from exchange-status 2026-09-13.  Every public method is
    non-blocking and never raises.  Failures are recorded in the snapshot as
    ``error`` and the previous good values are kept, so a VoIP.ms outage
    degrades to "last known balance, marked stale" rather than a blank panel.

    Injectable seams (all have safe defaults for live mode):
      ``http``        — callable(method, params) → dict.  Default: real urllib.
      ``clock``       — callable() → float.  Default: time.time.
      ``sleep``       — callable(secs).  Default: waits on stop event (exits in ≤ secs).
      ``cache_path``  — where to persist the snapshot.
      ``creds``       — callable() → (user, pw, did) OR a path string.
                         Default: reads _DEFAULT_CREDS file via _creds().
      ``legacy_cache``— legacy seed-cache path; read-once if our own is absent.
      ``subaccount``  — VoIP.ms sub-account name.
      ``intervals``   — per-section poll intervals in seconds.
      ``low_balance`` — balance threshold for ``balance_low``.
      ``stale_after`` — seconds until a snapshot is considered stale.
    """

    def __init__(
        self,
        *,
        http: Callable[[str, dict[str, str]], dict] | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        cache_path: str | None = None,
        creds: Callable[[], tuple[str, str, str]] | str | None = None,
        legacy_cache: str | None = None,
        subaccount: str | None = None,
        intervals: dict[str, int] | None = None,
        low_balance: float | None = None,
        stale_after: int | None = None,
    ) -> None:
        import time as _time  # noqa: PLC0415

        self._http = http if http is not None else _live_http
        self._clock = clock if clock is not None else _time.time
        self._cache_path = cache_path or _DEFAULT_CACHE
        self._legacy_cache = legacy_cache or _LEGACY_CACHE
        self._subaccount = subaccount or VOIPMS_SUBACCOUNT
        self._intervals = intervals or VOIPMS_INTERVALS
        self._low_balance = low_balance if low_balance is not None else VOIPMS_LOW_BALANCE
        self._stale_after = stale_after if stale_after is not None else VOIPMS_STALE_AFTER

        # Credentials: callable or path string. The label is what an error names: the
        # path, as legacy did (e:874-878), or "injected" for a callable.
        if callable(creds):
            self._creds = creds
            self._creds_label = "injected"
        else:
            creds_path = creds if isinstance(creds, str) else _DEFAULT_CREDS
            self._creds: Callable[[], tuple[str, str, str]] = (
                lambda p=creds_path: _creds(p)
            )
            self._creds_label = creds_path

        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Default sleep: waits on stop event so stop() wakes the loop immediately.
        if sleep is not None:
            self._sleep = sleep
        else:
            self._sleep = lambda secs: self._stop_event.wait(secs)

        self._data: dict[str, Any] = {
            "balance": None, "spent_today": None, "calls_today": None,
            "time_today": None, "spent_total": None, "calls_total": None,
            # ⭐ PROVENANCE SIBLINGS (legacy e:787–796). None = UNKNOWN, NOT False.
            "spent_today_measured": None, "calls_today_measured": None,
            "time_today_measured": None, "spent_total_measured": None,
            "calls_total_measured": None,
            "registered": None, "register_server": None, "register_ip": None,
            "register_next": None, "register_agent": None,
            "did_description": None, "did_sms_enabled": None,
            "did_e911": None, "did_next_billing": None, "did_routing": None,
            "fetched": {},
            "error": None,
        }
        # ⛔ NOT IN _data, THEREFORE NOT PERSISTED (legacy e:804–810).
        self._started = False
        self._load()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load state from disk.  Safe to call before start()."""
        for path, _is_legacy in (
            (self._cache_path, False),
            (self._legacy_cache, True),
        ):
            with contextlib.suppress(OSError, ValueError):
                with open(path, encoding="utf-8") as fh:
                    disk = json.load(fh)
                if isinstance(disk, dict):
                    self._data.update({k: v for k, v in disk.items()
                                       if k in _PERSIST})
                    # ⭐ SEED ONCE, FROM THE RETIRING SERVICE, READ-ONLY (e:825).
                    return

    def _save(self) -> None:
        """Write state to disk atomically (legacy e:837–845)."""
        with contextlib.suppress(OSError):
            state_dir = os.path.dirname(self._cache_path)
            os.makedirs(state_dir, exist_ok=True)
            tmp = self._cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({k: self._data[k] for k in _PERSIST
                           if k in self._data}, fh)
            os.replace(tmp, self._cache_path)  # atomic; never a torn file
        # (an OSError is suppressed: a cache we cannot persist is still a cache)

    def _call(self, method: str, user: str, pw: str, **params: str) -> dict:
        """Call the VoIP.ms REST API (legacy e:847–867)."""
        api_params = {"api_username": user, "api_password": pw,
                      "method": method, **params}
        try:
            body = self._http(method, api_params)
        except urllib.error.HTTPError as e:
            # ⛔ HTTP ERRORS BEFORE SCRUB (legacy e:855–859).
            hint = (
                " — a bare 403 here is usually the WAF rejecting the "
                "User-Agent, not the credentials or the IP whitelist"
                if e.code == 403 else ""
            )
            raise RuntimeError(f"{method}: HTTP {e.code}{hint}") from None
        except Exception as e:
            # ⛔ SCRUBBED, AND `from None` (legacy e:861–864).
            raise RuntimeError(_scrub(f"{method}: {e}", pw)) from None
        if body.get("status") != "success":
            raise RuntimeError(f"{method}: {body.get('status')}")
        return body

    def _refresh_once(self) -> None:
        """One poll cycle (legacy e:869–954)."""
        now = self._clock()
        try:
            user, pw, did = self._creds()
        except (OSError, KeyError) as e:
            with self._lock:
                # ⛔ NAMES THE PATH AND THE MISSING KEY; no value (legacy e:874–878).
                # The text is part of the snapshot's JSON contract: the legacy format.
                self._data["error"] = f"credentials unreadable ({self._creds_label}): {e}"
            return

        errs: list[str] = []
        with self._lock:
            fetched = dict(self._data["fetched"])
        due = [s for s, iv in self._intervals.items()
               if now - fetched.get(s, 0) >= iv]

        for section in due:
            try:
                if section == "balance":
                    b = self._call("getBalance", user, pw, advanced="true")["balance"]

                    def _m(key: str, _b: dict = b) -> tuple[Any, bool]:
                        raw = _b.get(key)
                        return raw, (raw not in (None, ""))

                    _st, _st_m = _m("spent_today")
                    _ct, _ct_m = _m("calls_today")
                    _tt, _tt_m = _m("time_today")
                    _sT, _sT_m = _m("spent_total")
                    _cT, _cT_m = _m("calls_total")
                    upd: dict[str, Any] = {
                        "balance": float(b["current_balance"]),
                        "spent_today": float(_st or 0),
                        "calls_today": int(_ct or 0),
                        "time_today": _tt,
                        "spent_total": float(_sT or 0),
                        "calls_total": int(_cT or 0),
                        "spent_today_measured": _st_m,
                        "calls_today_measured": _ct_m,
                        "time_today_measured": _tt_m,
                        "spent_total_measured": _sT_m,
                        "calls_total_measured": _cT_m,
                    }
                elif section == "registration":
                    r = self._call("getRegistrationStatus", user, pw,
                                   account=self._subaccount)
                    regs = r.get("registrations") or []
                    first = regs[0] if regs else {}
                    upd = {
                        "registered": r.get("registered") == "yes",
                        "register_server": first.get("server_hostname"),
                        "register_ip": first.get("register_ip"),
                        "register_next": first.get("register_next"),
                        "register_agent": first.get("register_useragent"),
                    }
                else:  # did
                    ds = self._call("getDIDsInfo", user, pw, did=did)["dids"]
                    d = ds[0] if ds else {}
                    upd = {
                        "did_description": d.get("description"),
                        "did_sms_enabled": d.get("sms_enabled") == "1",
                        "did_e911": d.get("e911") == "1",
                        "did_next_billing": d.get("next_billing"),
                        "did_routing": d.get("routing"),
                    }
            except Exception as e:
                errs.append(_scrub(e, pw))
                continue
            with self._lock:
                self._data.update(upd)
                self._data["fetched"][section] = self._clock()

        with self._lock:
            self._data["error"] = "; ".join(str(e) for e in errs) if errs else None
            self._save()

    def _loop(self) -> None:
        """Background poll loop (legacy e:956–965)."""
        # A short first delay lets the HTTP server bind and answer immediately.
        self._sleep(2)
        while not self._stop_event.is_set():
            with contextlib.suppress(Exception):   # never let the thread die
                self._refresh_once()
            self._sleep(30)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background thread (legacy e:968–975).  Idempotent."""
        with self._lock:
            if self._started:
                return
            self._started = True
        t = threading.Thread(target=self._loop, name="voipms-poller", daemon=True)
        t.start()

    def stop(self) -> None:
        """Signal the background loop to exit.  Returns immediately."""
        self._stop_event.set()

    def snapshot(self) -> dict[str, Any]:
        """Instant, non-blocking.  Never raises (legacy e:977–1003)."""
        import datetime  # noqa: PLC0415

        with self._lock:
            d = dict(self._data)
            fetched = dict(d.pop("fetched", {}))
            d["polling"] = self._started

        newest = max(fetched.values()) if fetched else 0
        now_ts = self._clock()
        age = int(now_ts - newest) if newest else None
        bal = d.get("balance")

        d["age"] = age
        d["stale"] = (age is None) or (age > self._stale_after)
        d["fetched_at"] = (
            datetime.datetime.fromtimestamp(newest)  # noqa: DTZ006
            .strftime("%Y-%m-%d %H:%M:%S") if newest else None
        )
        d["balance_low"] = (bal is not None and bal < self._low_balance)
        d["low_threshold"] = self._low_balance
        d["months_left"] = round(bal / 2.35, 1) if bal is not None else None
        d["days_to_billing"] = None
        if d.get("did_next_billing"):
            with contextlib.suppress(ValueError):
                nb = datetime.datetime.strptime(d["did_next_billing"], "%Y-%m-%d")
                now_dt = datetime.datetime.fromtimestamp(now_ts)  # noqa: DTZ006
                d["days_to_billing"] = (nb - now_dt).days
        return d
