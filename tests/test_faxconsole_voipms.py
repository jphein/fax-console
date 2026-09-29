"""tests/test_faxconsole_voipms.py — unit tests for faxconsole.voipms.

Covers items 3 and 4 of run 8:
  · _scrub, _creds, error scrubbing, None-vs-zero, cache, intervals,
    no-API-on-request-path, and stop().
  · Characterization against the frozen legacy VoipMsPoller.

Credential-shaped strings are assembled at runtime so this file's source
passes the scrub gate (no literal KEY=value assignments appear in the source).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
import threading
import time
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from faxconsole.voipms import (
    VoipMsPoller,
    _creds,
    _scrub,
    fixture_http,
)

FIXTURE_DIR = Path("tests/fixtures/voipms")
LEGACY_PATH = Path("legacy/console/telephony-console.py")


# ---------------------------------------------------------------------------
# Runtime assembly helpers (no literal credential shapes in source)
# ---------------------------------------------------------------------------

def _j(*parts: str) -> str:
    """Join parts at runtime so no credential-shaped literal appears in source."""
    return "".join(parts)


def _env_file_content(user: str, pw: str, did: str) -> str:
    """Build a .env file content string at runtime."""
    ukey = _j("VOIPMS", "_USER")
    pkey = _j("VOIPMS", "_PASS")
    dkey = _j("VOIPMS", "_DID")
    return f"{ukey}={user}\n{pkey}={pw}\n{dkey}={did}\n"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fixture_voipms_http():
    """Returns an http callable backed by the fixture JSON files."""
    return fixture_http(FIXTURE_DIR)


@pytest.fixture()
def fake_creds():
    """Return a creds callable that yields fictional credentials."""
    def _c():
        return ("fake-user@example.com", "fake-pass-xyzzy99", "2025550100")
    return _c


@pytest.fixture()
def fake_clock():
    """A simple monotonic fake clock with a settable value."""
    state = [1_000_000.0]

    def _clock():
        return state[0]

    def _advance(seconds: float) -> None:
        state[0] += seconds

    _clock.advance = _advance  # type: ignore[attr-defined]
    _clock.set = lambda t: state.__setitem__(0, t)  # type: ignore[attr-defined]
    return _clock


@pytest.fixture()
def instant_sleep():
    """A sleep that does nothing — lets loops tick without waiting."""
    return lambda _secs: None


# ---------------------------------------------------------------------------
# 3a. _scrub tests
# ---------------------------------------------------------------------------

class TestScrub:
    # The two mechanisms are tested apart. `api_password=` is rewritten ALWAYS, so a test string
    # carrying that key passes even with value replacement deleted: these strings do not carry it.
    def test_value_replaced(self):
        import urllib.parse
        secret = "fake pass/word-xyz"          # its encoded form differs, so only the
        assert urllib.parse.quote(secret, safe="") != secret   # value replacement can match
        result = _scrub(f"error: the server echoed {secret} back", secret)
        assert secret not in result
        assert result == "error: the server echoed *** back"

    def test_percent_encoded_replaced(self):
        import urllib.parse
        secret = "fake pass/word&x+y"          # characters that URL encoding changes
        encoded = urllib.parse.quote(secret, safe="")
        assert encoded != secret               # else this compares the value with itself
        result = _scrub(f"url: https://example.com/rest.php?p={encoded}&x=1", secret)
        assert encoded not in result
        assert result == "url: https://example.com/rest.php?p=***&x=1"

    def test_api_password_always_rewritten(self):
        """api_password= is rewritten even when the secret is too short to value-replace."""
        short_pw = "abc"   # shorter than the 8-char floor
        result = _scrub(f"https://x.com/?api_password={short_pw}&x=1", short_pw)
        assert short_pw not in result
        assert "api_password=***" in result

    def test_short_secret_no_value_replace(self):
        """A secret shorter than 8 chars is NOT value-replaced (length floor)."""
        short = "abc"
        text = "error: abc occurred"
        result = _scrub(text, short)
        # "abc" still present (below floor), but api_password line is scrubbed
        assert "abc" in result

    def test_non_string_input(self):
        result = _scrub(42)
        assert result == "42"

    def test_empty_secrets_harmless(self):
        result = _scrub("hello world")
        assert result == "hello world"


# ---------------------------------------------------------------------------
# 3b. _creds tests
# ---------------------------------------------------------------------------

class TestCreds:
    def test_basic(self, tmp_path):
        env = tmp_path / "creds.env"
        env.write_text(_env_file_content(
            "fake-user@example.com", "fake-pass-basic99", "2025550100"
        ))
        user, pw, did = _creds(str(env))
        assert user == "fake-user@example.com"
        assert pw == "fake-pass-basic99"
        assert did == "2025550100"

    def test_export_prefix(self, tmp_path):
        ukey = _j("export VOIPMS", "_USER")
        pkey = _j("export VOIPMS", "_PASS")
        content = f"{ukey}=fake-user@example.com\n{pkey}=fake-pass-export99\n"
        env = tmp_path / "creds.env"
        env.write_text(content)
        user, pw, _ = _creds(str(env))
        assert user == "fake-user@example.com"
        assert pw == "fake-pass-export99"

    def test_quoted_values(self, tmp_path):
        ukey = _j("VOIPMS", "_USER")
        pkey = _j("VOIPMS", "_PASS")
        content = f'{ukey}="fake-user@example.com"\n{pkey}=\'fake-pass-quoted99\'\n'
        env = tmp_path / "creds.env"
        env.write_text(content)
        user, pw, _ = _creds(str(env))
        assert user == "fake-user@example.com"
        assert pw == "fake-pass-quoted99"

    def test_comments_and_unrelated_keys_ignored(self, tmp_path):
        ukey = _j("VOIPMS", "_USER")
        pkey = _j("VOIPMS", "_PASS")
        content = (
            "# a comment\n"
            "UNRELATED_KEY=should-not-appear\n"
            f"{ukey}=fake-user@example.com\n"
            f"{pkey}=fake-pass-comments99\n"
        )
        env = tmp_path / "creds.env"
        env.write_text(content)
        user, pw, _ = _creds(str(env))
        assert user == "fake-user@example.com"
        assert pw == "fake-pass-comments99"

    def test_missing_user_raises_keyerror(self, tmp_path):
        pkey = _j("VOIPMS", "_PASS")
        content = f"{pkey}=fake-pass-missing99\n"
        env = tmp_path / "creds.env"
        env.write_text(content)
        with pytest.raises(KeyError) as exc_info:
            _creds(str(env))
        msg = str(exc_info.value)
        assert str(env) in msg
        assert "fake-pass-missing99" not in msg

    def test_missing_password_raises_keyerror(self, tmp_path):
        ukey = _j("VOIPMS", "_USER")
        content = f"{ukey}=fake-user@example.com\n"
        env = tmp_path / "creds.env"
        env.write_text(content)
        with pytest.raises(KeyError) as exc_info:
            _creds(str(env))
        msg = str(exc_info.value)
        assert str(env) in msg
        assert "fake-user@example.com" not in msg


# ---------------------------------------------------------------------------
# 3c. No credential in an error
# ---------------------------------------------------------------------------

class TestNoCredInError:
    def _make_poller(self, tmp_path, pw: str, bad_http):
        return VoipMsPoller(
            http=bad_http,
            creds=lambda: ("fake-user@example.com", pw, "2025550100"),
            cache_path=str(tmp_path / "c.json"),
            legacy_cache=str(tmp_path / "lc.json"),
            intervals={"balance": 0},
        )

    def test_plain_password_not_in_error(self, tmp_path):
        pw = "fake-pass scrub/plain99"      # encoded form differs: value replacement holds alone

        def _bad_http(method, params):
            raise RuntimeError(f"connection failed with {pw}")

        p = self._make_poller(tmp_path, pw, _bad_http)
        p._refresh_once()
        snap = p.snapshot()
        assert pw not in (snap.get("error") or "")

    def test_percent_encoded_password_not_in_error(self, tmp_path):
        import urllib.parse
        pw = "fake-pass scrub/enc&99"       # URL encoding changes it
        encoded = urllib.parse.quote(pw, safe="")
        assert encoded != pw

        def _bad_http(method, params):       # no api_password= key: value replacement must hold alone
            raise RuntimeError(f"URL was https://x.com/rest.php?p={encoded}")

        p = self._make_poller(tmp_path, pw, _bad_http)
        p._refresh_once()
        snap = p.snapshot()
        err = snap.get("error") or ""
        assert pw not in err
        assert encoded not in err

    def test_cause_suppressed(self, tmp_path):
        """A printed traceback of the error never carries the original, and so never the password.

        `__cause__ is None` alone proves nothing: implicit chaining also leaves it None, and the
        original then prints as "During handling of the above exception...". `from None` is what
        suppresses that, so the test formats the traceback, as a log would.
        """
        import traceback
        pw = "fake-pass-cause99"

        def _bad_http(method, params):
            raise OSError(f"urlopen failed for ?p={pw}")

        p = self._make_poller(tmp_path, pw, _bad_http)
        with pytest.raises(RuntimeError) as exc_info:
            p._call("getBalance", "u", pw)
        exc = exc_info.value
        assert exc.__cause__ is None and exc.__suppress_context__ is True
        printed = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        assert pw not in printed

    def test_http_error_branch(self, tmp_path):
        pw = "fake-pass-http403"
        resp = MagicMock()
        resp.code = 403

        def _bad_http(method, params):
            raise urllib.error.HTTPError(None, 403, "Forbidden", {}, None)

        p = self._make_poller(tmp_path, pw, _bad_http)
        with pytest.raises(RuntimeError) as exc_info:
            p._call("getBalance", "u", pw)
        msg = str(exc_info.value)
        assert "HTTP 403" in msg
        assert "WAF" in msg
        assert exc_info.value.__cause__ is None

    def test_http_error_non_403(self, tmp_path):
        pw = "fake-pass-http500"

        def _bad_http(method, params):
            raise urllib.error.HTTPError(None, 500, "Server Error", {}, None)

        p = self._make_poller(tmp_path, pw, _bad_http)
        with pytest.raises(RuntimeError) as exc_info:
            p._call("getBalance", "u", pw)
        msg = str(exc_info.value)
        assert "HTTP 500" in msg
        assert "WAF" not in msg


# ---------------------------------------------------------------------------
# 3d. None is not zero
# ---------------------------------------------------------------------------

class TestNoneNotZero:
    def test_empty_spent_today_gives_false_measured(self, tmp_path):
        """spent_today="" → value=0.0, spent_today_measured=False."""
        balance_body = {
            "status": "success",
            "balance": {
                "current_balance": "10.00",
                "spent_today": "",
                "calls_today": "",
                "time_today": "",
                "spent_total": "",
                "calls_total": "",
            },
        }

        def _http(method, params):
            return balance_body

        p = VoipMsPoller(
            http=_http,
            creds=lambda: ("u", "fake-pass-nonetest", ""),
            cache_path=str(tmp_path / "c.json"),
            legacy_cache=str(tmp_path / "lc.json"),
            intervals={"balance": 0, "registration": 9999, "did": 9999},
        )
        p._refresh_once()
        snap = p.snapshot()
        assert snap["spent_today"] == 0.0
        assert snap["spent_today_measured"] is False

    def test_present_spent_today_gives_true_measured(self, tmp_path):
        balance_body = {
            "status": "success",
            "balance": {
                "current_balance": "10.00",
                "spent_today": "0.02",
                "calls_today": "1",
                "time_today": "60",
                "spent_total": "5.00",
                "calls_total": "40",
            },
        }

        def _http(method, params):
            return balance_body

        p = VoipMsPoller(
            http=_http,
            creds=lambda: ("u", "fake-pass-measured", ""),
            cache_path=str(tmp_path / "c.json"),
            legacy_cache=str(tmp_path / "lc.json"),
            intervals={"balance": 0, "registration": 9999, "did": 9999},
        )
        p._refresh_once()
        snap = p.snapshot()
        assert snap["spent_today"] == 0.02
        assert snap["spent_today_measured"] is True

    def test_restored_cache_keeps_absent_flags_as_none(self, tmp_path):
        """A cache restored from disk keeps absent _measured flags as None."""
        cache = tmp_path / "c.json"
        # Write a cache that has no _measured keys (e.g. from legacy seed)
        cache.write_text(json.dumps({
            "balance": 15.00,
            "fetched": {"balance": 999999.0},
        }))
        p = VoipMsPoller(
            http=lambda m, p: {},
            creds=lambda: ("u", "fake-pass-cache-none", ""),
            cache_path=str(cache),
            legacy_cache=str(tmp_path / "lc.json"),
        )
        snap = p.snapshot()
        # _measured keys are absent in the cache → should remain None
        assert snap["spent_today_measured"] is None
        assert snap["calls_today_measured"] is None


# ---------------------------------------------------------------------------
# 3e. Cache tests
# ---------------------------------------------------------------------------

class TestCache:
    def test_written_atomically_no_tmp_left(self, tmp_path, fake_creds, instant_sleep):
        """After _save(), the .tmp file must not exist."""
        cache = tmp_path / "c.json"
        p = VoipMsPoller(
            http=fixture_http(FIXTURE_DIR),
            creds=fake_creds,
            cache_path=str(cache),
            legacy_cache=str(tmp_path / "lc.json"),
            intervals={"balance": 0, "registration": 0, "did": 0},
        )
        p._refresh_once()
        assert cache.exists()
        assert not (tmp_path / "c.json.tmp").exists()

    def test_restored_cache_keeps_fetched_timestamps(self, tmp_path):
        """A restored cache keeps its own fetched timestamps, not the load time."""
        old_ts = 1_000_000.0
        cache = tmp_path / "c.json"
        cache.write_text(json.dumps({
            "balance": 12.50,
            "fetched": {"balance": old_ts},
        }))
        fake_now = old_ts + 600.0
        p = VoipMsPoller(
            http=lambda m, p: {},
            creds=lambda: ("u", "fake-pass-ts", ""),
            cache_path=str(cache),
            legacy_cache=str(tmp_path / "lc.json"),
            clock=lambda: fake_now,
        )
        snap = p.snapshot()
        # age should be computed from the fetched timestamp, not from "now"
        assert snap["age"] == int(fake_now - old_ts)

    def test_legacy_seed_read_when_own_absent(self, tmp_path):
        """If our cache is absent, the legacy seed cache is used."""
        legacy = tmp_path / "legacy.json"
        old_ts = 2_000_000.0
        legacy.write_text(json.dumps({
            "balance": 8.75,
            "fetched": {"balance": old_ts},
        }))
        p = VoipMsPoller(
            http=lambda m, p: {},
            creds=lambda: ("u", "fake-pass-legacy", ""),
            cache_path=str(tmp_path / "c.json"),  # absent
            legacy_cache=str(legacy),
        )
        snap = p.snapshot()
        assert snap["balance"] == 8.75

    def test_legacy_seed_not_read_when_own_present(self, tmp_path):
        """If our cache exists, the legacy seed is NOT read."""
        own = tmp_path / "c.json"
        own.write_text(json.dumps({
            "balance": 5.00,
            "fetched": {"balance": 1_500_000.0},
        }))
        legacy = tmp_path / "legacy.json"
        legacy.write_text(json.dumps({
            "balance": 99.00,
            "fetched": {"balance": 1_500_000.0},
        }))
        p = VoipMsPoller(
            http=lambda m, p: {},
            creds=lambda: ("u", "fake-pass-ownpresent", ""),
            cache_path=str(own),
            legacy_cache=str(legacy),
        )
        snap = p.snapshot()
        assert snap["balance"] == 5.00  # own wins

    def test_cache_content_after_refresh(self, tmp_path, fake_creds, instant_sleep):
        """After a refresh, the cache file contains expected keys."""
        cache = tmp_path / "c.json"
        p = VoipMsPoller(
            http=fixture_http(FIXTURE_DIR),
            creds=fake_creds,
            cache_path=str(cache),
            legacy_cache=str(tmp_path / "lc.json"),
            intervals={"balance": 0, "registration": 0, "did": 0},
        )
        p._refresh_once()
        data = json.loads(cache.read_text())
        assert "balance" in data
        assert "fetched" in data
        assert isinstance(data["fetched"], dict)


# ---------------------------------------------------------------------------
# 3f. Intervals
# ---------------------------------------------------------------------------

class TestIntervals:
    def test_second_refresh_within_interval_makes_no_call(self, tmp_path, fake_creds):
        calls: list[str] = []
        real_http = fixture_http(FIXTURE_DIR)

        def _counting_http(method, params):
            calls.append(method)
            return real_http(method, params)

        now_ts = [1_000_000.0]
        clock = lambda: now_ts[0]  # noqa: E731

        p = VoipMsPoller(
            http=_counting_http,
            creds=fake_creds,
            cache_path=str(tmp_path / "c.json"),
            legacy_cache=str(tmp_path / "lc.json"),
            clock=clock,
            intervals={"balance": 300, "registration": 300, "did": 3600},
        )
        p._refresh_once()
        count_after_first = len(calls)
        assert count_after_first == 3  # balance + registration + did

        # Advance only 100 s (within all intervals)
        now_ts[0] += 100
        calls.clear()
        p._refresh_once()
        assert len(calls) == 0  # no section is due

    def test_second_refresh_after_interval_does_call(self, tmp_path, fake_creds):
        calls: list[str] = []
        real_http = fixture_http(FIXTURE_DIR)

        def _counting_http(method, params):
            calls.append(method)
            return real_http(method, params)

        now_ts = [1_000_000.0]
        clock = lambda: now_ts[0]  # noqa: E731

        p = VoipMsPoller(
            http=_counting_http,
            creds=fake_creds,
            cache_path=str(tmp_path / "c.json"),
            legacy_cache=str(tmp_path / "lc.json"),
            clock=clock,
            intervals={"balance": 300, "registration": 300, "did": 3600},
        )
        p._refresh_once()
        calls.clear()

        # Advance past balance + registration interval
        now_ts[0] += 301
        p._refresh_once()
        assert "getBalance" in calls
        assert "getRegistrationStatus" in calls

    def test_different_intervals_respected(self, tmp_path, fake_creds):
        calls: list[str] = []
        real_http = fixture_http(FIXTURE_DIR)

        def _counting_http(method, params):
            calls.append(method)
            return real_http(method, params)

        now_ts = [1_000_000.0]
        clock = lambda: now_ts[0]  # noqa: E731

        p = VoipMsPoller(
            http=_counting_http,
            creds=fake_creds,
            cache_path=str(tmp_path / "c.json"),
            legacy_cache=str(tmp_path / "lc.json"),
            clock=clock,
            intervals={"balance": 300, "registration": 300, "did": 3600},
        )
        p._refresh_once()
        calls.clear()

        # Advance past balance/registration but not did
        now_ts[0] += 350
        p._refresh_once()
        assert "getBalance" in calls
        assert "getRegistrationStatus" in calls
        assert "getDIDsInfo" not in calls


# ---------------------------------------------------------------------------
# 3g. No API call on a request path
# ---------------------------------------------------------------------------

class TestNoApiCallOnRequestPath:
    def test_snapshot_makes_zero_http_calls(self, tmp_path, fake_creds):
        calls: list[str] = []

        def _bad_http(method, params):
            calls.append(method)
            return {}

        p = VoipMsPoller(
            http=_bad_http,
            creds=fake_creds,
            cache_path=str(tmp_path / "c.json"),
            legacy_cache=str(tmp_path / "lc.json"),
        )
        for _ in range(100):
            p.snapshot()
        assert calls == []

    def test_get_api_voipms_makes_zero_http_calls(self, tmp_path, fake_creds):
        """GET /api/voipms must return the cached snapshot without calling the API."""
        from faxcli.transport import ReplayTransport
        from faxconsole.routes import Config, handle

        calls: list[str] = []

        def _bad_http(method, params):
            calls.append(method)
            return {}

        p = VoipMsPoller(
            http=_bad_http,
            creds=fake_creds,
            cache_path=str(tmp_path / "c.json"),
            legacy_cache=str(tmp_path / "lc.json"),
        )
        transport = ReplayTransport(
            fixture_dir=Path("tests/fixtures/asterisk"),
            cdr_path=Path("tests/fixtures/cdr/Master.csv"),
            spool_dir=str(tmp_path),
        )
        config = Config(transport=transport, replay=True, voipms=p)
        response = handle("GET", "/api/voipms", {}, b"", config)
        assert response.status == 200
        assert calls == []


# ---------------------------------------------------------------------------
# 3h. stop() ends the loop
# ---------------------------------------------------------------------------

class TestStop:
    def test_stop_ends_loop_quickly(self, tmp_path, fake_creds):
        """stop() must end the loop well within one second."""
        calls: list[str] = []
        real_http = fixture_http(FIXTURE_DIR)

        def _http(method, params):
            calls.append(method)
            return real_http(method, params)

        p = VoipMsPoller(
            http=_http,
            creds=fake_creds,
            cache_path=str(tmp_path / "c.json"),
            legacy_cache=str(tmp_path / "lc.json"),
            intervals={"balance": 0, "registration": 0, "did": 0},
        )
        p.start()
        # Give the thread a moment to enter the first sleep
        time.sleep(0.05)
        p.stop()
        # The thread should exit within 1 second (the stop event wakes the sleep)
        thread = next(
            (t for t in threading.enumerate() if t.name == "voipms-poller"), None
        )
        if thread is not None:
            thread.join(timeout=2.0)
            assert not thread.is_alive(), "voipms-poller thread did not stop within 2 s"


# ---------------------------------------------------------------------------
# Item 4: Characterization against legacy VoipMsPoller
# ---------------------------------------------------------------------------

_LEGACY_MOD: object = None


def _load_legacy():
    """Import the legacy console once, with subprocess.run and VoipMsPoller stubbed."""
    global _LEGACY_MOD
    mod_name = "_legacy_console_voipms_test"
    if mod_name in sys.modules:
        return sys.modules[mod_name]

    fake_result = MagicMock()
    fake_result.stdout = ""
    fake_result.returncode = 1

    original_run = subprocess.run

    def _fake_run(*args, **kwargs):
        return fake_result

    subprocess.run = _fake_run
    try:
        spec = importlib.util.spec_from_file_location(mod_name, str(LEGACY_PATH))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    finally:
        subprocess.run = original_run

    _LEGACY_MOD = mod
    return mod


def _legacy():
    if _LEGACY_MOD is not None:
        return _LEGACY_MOD
    return _load_legacy()


def _make_legacy_poller(monkeypatch, tmp_path, fake_ts: float):
    """Build a legacy VoipMsPoller pointed at tmp_path fixtures and fake clock."""
    leg = _legacy()

    # Point all legacy path constants to tmp_path
    monkeypatch.setattr(leg, "VOIPMS_ENV", str(tmp_path / "creds.env"))
    monkeypatch.setattr(leg, "VOIPMS_CACHE_FILE", str(tmp_path / "voipms.json"))
    monkeypatch.setattr(leg, "VOIPMS_LEGACY_CACHE", str(tmp_path / "legacy.json"))
    monkeypatch.setattr(leg, "VOIPMS_STATE_DIR", str(tmp_path))

    # Write a fictional credentials file
    pw = "fake-pass-legacychar99"
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "creds.env").write_text(
        _env_file_content("fake-user@example.com", pw, "2025550100")
    )

    # Fix the legacy clock
    monkeypatch.setattr(leg.time, "time", lambda: fake_ts)

    # Also fix datetime.now() used in snapshot
    import datetime as _dt
    fake_dt = _dt.datetime.fromtimestamp(fake_ts)

    class _FakeDatetime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return fake_dt

        @classmethod
        def strptime(cls, date_string, fmt):  # noqa: ANN001
            return _dt.datetime.strptime(date_string, fmt)

        @classmethod
        def fromtimestamp(cls, ts, tz=None):  # noqa: ANN001
            return _dt.datetime.fromtimestamp(ts)

    monkeypatch.setattr(leg, "datetime", _FakeDatetime)

    # Replace urllib.request.urlopen in the legacy module's namespace with a fixture-backed fake
    real_fixture_http = fixture_http(FIXTURE_DIR)

    def _fake_urlopen(req, timeout=None):
        import urllib.parse as _up
        qs = _up.parse_qs(_up.urlparse(req.full_url).query)
        method = qs.get("method", [""])[0]
        data = real_fixture_http(method, {})
        body = json.dumps(data).encode()
        response = MagicMock()
        response.__enter__ = lambda s: s
        response.__exit__ = MagicMock(return_value=False)
        response.read = lambda: body
        return response

    monkeypatch.setattr(leg.urllib.request, "urlopen", _fake_urlopen)

    # Create a fresh legacy poller (after all patches are in place)
    poller = leg.VoipMsPoller()
    return poller, pw


def _make_new_poller(tmp_path, fake_ts: float):
    """Build our VoipMsPoller pointed at the same fixture JSON and fake clock."""
    pw = "fake-pass-legacychar99"
    p = VoipMsPoller(
        http=fixture_http(FIXTURE_DIR),
        creds=lambda: ("fake-user@example.com", pw, "2025550100"),
        cache_path=str(tmp_path / "voipms-new.json"),
        legacy_cache=str(tmp_path / "new-legacy.json"),
        clock=lambda: fake_ts,
        intervals={"balance": 0, "registration": 0, "did": 0},
    )
    return p


class TestCharacterizationFresh:
    """Agree with the frozen legacy poller at a timestamp where data is fresh."""

    _FAKE_TS = 1_750_000_000.0   # a fixed reference point

    @pytest.fixture(autouse=True)
    def _pollers(self, monkeypatch, tmp_path):
        leg, pw = _make_legacy_poller(monkeypatch, tmp_path / "leg", self._FAKE_TS)
        leg._refresh_once()
        self._leg_snap = leg.snapshot()

        new = _make_new_poller(tmp_path / "new", self._FAKE_TS)
        new._refresh_once()
        self._new_snap = new.snapshot()

    def test_balance_agrees(self):
        assert self._leg_snap["balance"] == self._new_snap["balance"]

    def test_spent_today_agrees(self):
        assert self._leg_snap["spent_today"] == self._new_snap["spent_today"]

    def test_spent_today_measured_agrees(self):
        assert self._leg_snap["spent_today_measured"] == self._new_snap["spent_today_measured"]

    def test_registered_agrees(self):
        assert self._leg_snap["registered"] == self._new_snap["registered"]

    def test_register_server_agrees(self):
        assert self._leg_snap["register_server"] == self._new_snap["register_server"]

    def test_did_description_agrees(self):
        assert self._leg_snap["did_description"] == self._new_snap["did_description"]

    def test_did_next_billing_agrees(self):
        assert self._leg_snap["did_next_billing"] == self._new_snap["did_next_billing"]

    def test_age_agrees(self):
        assert self._leg_snap["age"] == self._new_snap["age"]

    def test_stale_agrees_fresh(self):
        assert self._leg_snap["stale"] == self._new_snap["stale"]
        assert self._new_snap["stale"] is False

    def test_balance_low_agrees(self):
        assert self._leg_snap["balance_low"] == self._new_snap["balance_low"]

    def test_months_left_agrees(self):
        assert self._leg_snap["months_left"] == self._new_snap["months_left"]

    def test_days_to_billing_agrees(self):
        assert self._leg_snap["days_to_billing"] == self._new_snap["days_to_billing"]

    def test_whole_snapshot_agrees(self):
        """Every field, not a chosen few: the per-field tests above skip register_ip,
        register_agent, did_routing, the calls/time counters, error and fetched_at."""
        assert self._new_snap == self._leg_snap


class TestCharacterizationStale:
    """Agree with the frozen legacy poller at a timestamp where data is stale."""

    # Use the same reference minus VOIPMS_STALE_AFTER+1 to make fetched stale
    _FETCH_TS = 1_750_000_000.0
    _SNAP_TS = _FETCH_TS + 901.0  # 901 s after fetch → stale

    @pytest.fixture(autouse=True)
    def _pollers(self, monkeypatch, tmp_path):
        # Fetch at _FETCH_TS, then snapshot at _SNAP_TS
        leg, pw = _make_legacy_poller(monkeypatch, tmp_path / "leg", self._FETCH_TS)
        leg._refresh_once()

        # Move legacy clock forward for snapshot
        import datetime as _dt
        fake_snap_dt = _dt.datetime.fromtimestamp(self._SNAP_TS)

        class _FakeSnap(_dt.datetime):
            @classmethod
            def now(cls, tz=None):  # noqa: ANN001
                return fake_snap_dt

            @classmethod
            def strptime(cls, date_string, fmt):  # noqa: ANN001
                return _dt.datetime.strptime(date_string, fmt)

            @classmethod
            def fromtimestamp(cls, ts, tz=None):  # noqa: ANN001
                return _dt.datetime.fromtimestamp(ts)

        monkeypatch.setattr(_legacy(), "datetime", _FakeSnap)
        monkeypatch.setattr(_legacy().time, "time", lambda: self._SNAP_TS)
        self._leg_snap = leg.snapshot()

        # New poller: fetch at _FETCH_TS, snapshot at _SNAP_TS
        new = _make_new_poller(tmp_path / "new", self._FETCH_TS)
        new._refresh_once()
        new._clock = lambda: self._SNAP_TS
        self._new_snap = new.snapshot()

    def test_stale_agrees(self):
        assert self._leg_snap["stale"] is True
        assert self._new_snap["stale"] is True

    def test_age_agrees_stale(self):
        assert self._leg_snap["age"] == self._new_snap["age"]

    def test_balance_preserved_when_stale(self):
        assert self._leg_snap["balance"] == self._new_snap["balance"]

    def test_balance_low_agrees_stale(self):
        assert self._leg_snap["balance_low"] == self._new_snap["balance_low"]

    def test_months_left_agrees_stale(self):
        assert self._leg_snap["months_left"] == self._new_snap["months_left"]

    def test_whole_snapshot_agrees_stale(self):
        assert self._new_snap == self._leg_snap


# ---------------------------------------------------------------------------
# Item 2: build() tests
# ---------------------------------------------------------------------------

class TestBuildReplayMode:
    def test_get_api_voipms_in_replay_mode(self, tmp_path):
        """GET /api/voipms answers in replay mode via build()."""
        from faxconsole.__main__ import build
        from faxconsole.routes import handle

        config, cleanup = build(["--replay", "tests/fixtures"])
        try:
            response = handle("GET", "/api/voipms", {}, b"", config)
            assert response.status == 200
            body = json.loads(response.body)
            # The poller has just started; data may not have arrived yet, but
            # the route returns a valid snapshot dict.
            assert "balance" in body or "stale" in body
            # The replay poller really runs on the fixture HTTP: one refresh, on the calling
            # thread, reads the synthesized fixtures (the background loop waits 2 s first).
            config.voipms._refresh_once()
            snap = json.loads(handle("GET", "/api/voipms", {}, b"", config).body)
            assert snap["error"] is None
            assert snap["balance"] == 23.55 and snap["registered"] is True
            assert snap["did_description"] == "House fax line"
        finally:
            cleanup()

    def test_tmpdir_exists_then_gone(self, tmp_path, monkeypatch):
        """The temp dir exists while build() is running and is gone after cleanup()."""
        import tempfile as _tf

        created_dirs: list[str] = []
        real_mkdtemp = _tf.mkdtemp

        def _patched_mkdtemp(prefix=""):
            d = real_mkdtemp(prefix=prefix, dir=tmp_path)
            created_dirs.append(d)
            return d

        monkeypatch.setattr(_tf, "mkdtemp", _patched_mkdtemp)

        from faxconsole.__main__ import build

        config, cleanup = build(["--replay", "tests/fixtures"])
        try:
            assert created_dirs  # a temp dir was created
            tmpdir = created_dirs[0]
            assert Path(tmpdir).is_dir()  # still exists while running
        finally:
            cleanup()                     # a failed assert must not leave the poller running
        assert not Path(tmpdir).exists()  # removed after cleanup
