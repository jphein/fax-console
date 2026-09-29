Week 2, run 8. Finish the VoIP.ms port that you started in run 7. Read these first:
- `AGENTS.md`;
- `faxconsole/voipms.py`, which you wrote in run 7;
- legacy `VoipMsPoller` and its helpers (e:681–1006 of `legacy/console/telephony-console.py`);
- `tests/test_faxconsole_pbx.py`, which shows how to import the frozen legacy console read-only.

Never edit `legacy/`, `tests/test_sandbox_guard.py` or `tests/conftest.py`. All existing tests must stay green.

**Keep a work log.** After each numbered item below, append one line to `WORKLOG.md` at the repo root: the item, the files changed, and the test count. Your last four runs reached their cost cap before their final summary, so the work log is the summary. Start it before item 1.

**1. Review fixes in `faxconsole/voipms.py`:**
- a. `snapshot()` must use the injected clock everywhere. `days_to_billing` still calls `datetime.now()`.
- b. Keep legacy's `HTTPError` branch (e:855–859). An HTTP error becomes `"<method>: HTTP <code>"`, plus the 403 hint about the WAF and the User-Agent, raised `from None`. The live `http` callable raises `urllib.error.HTTPError`, and `_call` must map it as legacy did.
- c. `stop()` must end the loop within one tick, not after up to 30 s. Make the default `sleep` wait on the stop event.
- d. Make ruff clean. There are 6 findings, including B023: pass the balance dict to the helper instead of closing over the loop variable.

**2. Replay mode.**
- Add `fixture_http(dir)`, which returns an `http(method, params)` callable. It serves `dir/<method>.json`, raises for an unknown method, and never touches the network.
- Make the credentials source injectable, for example a `creds` callable that defaults to reading the file. Replay mode then needs no credentials file and uses fictional values.
- Move the mode wiring in `faxconsole/__main__.py` into a function a test can call without binding, such as `build(argv) -> (config, cleanup)`. In replay mode it:
  - creates the temp dir;
  - builds the poller on `fixture_http(DIR / "voipms")`, with its cache inside the temp dir;
  - starts the poller and passes it as `Config(voipms=…)`.

  `cleanup()` stops the poller and removes the temp dir. `main()` calls it on shutdown, including on SIGTERM: systemd stops services with SIGTERM, which skips `finally` unless a handler turns it into an exit.
- Test through `build()` and `handle()`:
  - `GET /api/voipms` answers in replay mode;
  - the temp dir exists while running and is gone after `cleanup()`.

**3. Tests** in `tests/test_faxconsole_voipms.py`, 25 or more:
- **`_scrub`:** the value is removed, and so is its percent-encoded form; `api_password=` is always rewritten; the length floor holds (a short secret is not value-replaced, but `api_password=` still is).
- **`_creds`:** `export` prefixes, quoted values, comments and unrelated keys. A missing user or password raises `KeyError`, which names the path and never a value.
- **No credential in an error:** use an `http` that raises with the password in its message, both plain and percent-encoded. The snapshot's `error` carries neither form, and `__cause__` is suppressed.
- **`None` is not zero:** an empty `spent_today` gives `0.0` with `spent_today_measured` False, and a restored cache keeps absent flags as `None`.
- **The cache:**
  - it is written atomically, with no `.tmp` left behind;
  - a restored cache keeps its own `fetched` timestamps, so `age` comes from them;
  - the legacy seed cache is read only when our own cache is absent.
- **Intervals:** on a fake clock, a second refresh within an interval makes no call, and after it does.
- **No API call on a request path:** `snapshot()` called 100 times, and `GET /api/voipms`, make zero `http` calls.
- **`stop()`:** it ends the loop.

**4. Characterization** against the frozen legacy `VoipMsPoller`. Import it the way `tests/test_faxconsole_pbx.py` does. Then, with monkeypatch:
- point legacy's `VOIPMS_ENV`, `VOIPMS_CACHE_FILE`, `VOIPMS_LEGACY_CACHE` and `VOIPMS_STATE_DIR` at `tmp_path`;
- replace its `urllib.request.urlopen` with a fake that serves the same fixture JSON, chosen by the `method` query parameter;
- fix its clock (`time.time`, and `datetime` in the legacy module's namespace).

Run one `_refresh_once()` on each poller, then assert that `snapshot()` agrees field by field, including `age`, `stale`, `balance_low`, `months_left` and `days_to_billing`. Do it at two clock values, fresh and stale.

**Test data.** The scrub gate refused run 7's test file because a credential-shaped assignment appeared in it literally.
- Assemble the credentials file content at runtime, building the key names from parts (see `j()` in `tests/test_sandbox_guard.py`).
- Use a fictional value of the form `fake-…`.
- When you assert on the query-string form, build that substring at runtime too.

No test may open a socket or reach a network: conftest now fails any test that binds or connects an IP socket.

`.venv/bin/python -m pytest -q` must show 0 failures, and `.venv/bin/ruff check .` must be clean. End with a short summary: what changed for each numbered item, the test count before and after, and anything in this review you disagree with, with the reason.
