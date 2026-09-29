# Modernization analysis

Every factual claim cites `legacy/` by file and line. Fictional numbers are used throughout.

---

## 1. Summary

**The CLI** (`legacy/fax/fax/cli.py`) is a 288-line Python 3 program that converts a PDF to a
Group-4 TIFF with ghostscript, copies the TIFF to the PBX if needed, and originates a call via
`asterisk -rx 'channel originate PJSIP/…@voipms-fax application SendFax …,f'`. It also reads
back the CDR, the fax-show-stats counters, and the PJSIP registration status. It emits JSON with
`--json` for every subcommand.

**The console excerpt** (`legacy/console/telephony-console.py`) is a slice of an 11,858-line
single-file stdlib HTTP server that runs on the PBX. The kept region (3,009 lines) includes the
Fax panel, PBX/VoIP.ms status readers, the CDR reader, write authentication, and the HTTP
handler. It shells out to the CLI for all fax work.

**How they connect.** The console calls `fax --local --json {status,log,send}` and parses the
JSON it prints (console:2013, cli:122–244). The `--local` flag skips SSH; the console runs as
the `asterisk` user on the PBX and therefore needs no sudo (cli:63–66).

**Five findings that matter most.**

1. **`norm_number` and `fax_send` duplicate validation.** Number normalisation and N11 blocking
   appear in both programs (cli:39–47, console:2060–2066). Drift is a correctness risk.
2. **Every I/O call in the CLI raises `SystemExit`**, which exits the process. Library code must
   not call `SystemExit`; the console's `fax_cli()` caller relies on non-zero exit codes instead.
3. **The PDF written by `fax_send` is never cleaned up.** It is parked in `FAX_INBOX` and the
   TIFF is left in `SPOOL` after the send (console:2078–2083, cli:110–116).
4. **`utc_to_local` swallows all timezone errors** and returns the raw UTC string silently
   (cli:195–203). The console renders times without warning if `zoneinfo` or `FAX_TZ` is wrong.
5. **`wait_for` and all Asterisk reads use brittle text parsing.** Three different regex patterns
   match Asterisk CLI output that has no stable schema. Any Asterisk upgrade can silently break
   status reporting (cli:145–153, 219–231, console:1014–1020).

---

## 2. Module map of the console excerpt

| Region | Lines | What it does | Depends on |
|---|---|---|---|
| CSS constants (`TOKENS_CSS`, `STATUS_CSS`) | 62–346 | Design tokens, shared across pages | nothing |
| Identity / realm-sigil | 349–454 | `/api/version`, build hash, name generation | `subprocess`, `time` |
| Constants | 457–498 | Paths, ports, bind address, VoIP.ms intervals | `os.environ` |
| Background thread registry | 519–609 | `start_background`, `background_thread_audit` | `threading` |
| Consumer tally | 612–678 | Per-port request tally, capped at 400 entries | `threading` |
| VoIP.ms credential reader | 715–757 | Reads three keys from the env file, discards rest | file I/O |
| `VoipMsPoller` | 760–1003 | Background poll for balance, registration, DID info; JSON cache | `urllib`, `threading`, file I/O |
| Asterisk readers | 1009–1136 | `ast()`, `read_trunk()`, `read_calls()`, `read_sip_endpoints()` | `subprocess`, `re` |
| CDR + recordings | 1140–1222 | `read_cdr()`, `recordings_index()`, `describe()` | file I/O, `csv`, `re` |
| `snapshot()` | 1226–1250 | Parallel gather of all readers via `ThreadPoolExecutor` | all readers |
| PAGE template | 1261–1989 | HTML/CSS/JS for the console page | string substitution |
| Fax back end | 2004–2090 | `fax_cli`, `fax_state`, `_multipart`, `fax_send` | `subprocess`, `email.parser` |
| Write auth | 2097–2653 | `AUTH_JS`, token check, `write_authorized`, `writes_state` | `hmac`, `os.environ` |
| HTTP handler `H` | 2705–2975 | Routes, audio serving, doc serving | everything above |
| `main` | 2978–3037 | Bind, extra ports, start VoIP.ms poller | `ThreadingHTTPServer` |

**Fax panel request flow (end to end).**

```
Browser
  → GET /api/fax
  → H.do_GET (console:2885)
  → fax_state() (console:2030–2037)
      → fax_cli("status") (console:2013)  [subprocess: fax --local --json status]
      → fax_cli("log", "--limit", "25")   [subprocess: fax --local --json log]
          → in cli.py: cmd_status / cmd_log
              → asterisk("fax show stats", local=True)  [subprocess: asterisk -rx '…']
              → asterisk("pjsip show endpoint voipms-fax", …) etc.
              → cdr_rows() / fax_rows()   [reads /var/log/asterisk/cdr-csv/Master.csv]
          → cli emits JSON to stdout
      → fax_state returns {ok, status, log, …}
  ← JSON response

Browser
  → POST /api/fax/send (multipart/form-data with PDF + number + label + confirm=yes)
  → H.do_POST (console:2953)
  → write_authorized() (console:2914)  [checks X-Auth-Token header via hmac.compare_digest]
  → reads body up to FAX_MAX_BYTES+65536 (console:2959–2966)
  → _multipart(ctype, body) (console:2040)
  → fax_send(fields, files) (console:2058)
      → validates number (console:2060–2066)
      → writes PDF to FAX_INBOX (console:2076–2082)
      → fax_cli("send", path, number, "--label", label, timeout=90) (console:2083)
          → in cli.py: cmd_send
              → norm_number(), pdf_to_tiff() [ghostscript subprocess]
              → asterisk("channel originate …") [asterisk subprocess]
              → optionally wait_for() [polls asterisk, reads CDR]
          → cli emits JSON
      ← returns {ok, number, pages, tif, detail, …}
  ← JSON response
```

**PBX status flow.**

```
Browser → GET /api/state → H.do_GET (console:2835–2838) → snapshot() (console:1226)
  ThreadPoolExecutor(max_workers=7) submits:
    read_trunk()       → ast("pjsip show registrations")    → subprocess
    read_calls()       → ast("core show channels")           → subprocess
    read_sip_endpoints()→ ast("pjsip show endpoints")       → subprocess
    read_cdr()         → open(CDR)                           → file I/O
    [+ elided: read_femtocell, read_services, read_hlr]
  ← returns merged dict as JSON
```

**VoIP.ms poller thread.**

`VoipMsPoller._loop` (console:956) wakes every 30 s, calls `_refresh_once` (console:869), which
reads intervals from `VOIPMS_INTERVALS` (`{"balance": 300, "registration": 300, "did": 3600}`,
console:470) and issues HTTPS calls to `https://voip.ms/api/v1/rest.php` only when due. Results
are held under `_lock` and written atomically to `VOIPMS_CACHE_FILE` (console:842–843). The
`/api/voipms` route returns only the in-memory snapshot — never an API call (console:2859–2861).

---

## 3. CLI map

| Function | Class | I/O seam if I/O |
|---|---|---|
| `on_exchange()` | I/O | inject `hostname_fn=socket.gethostname` |
| `norm_number(s)` | **Pure** | — |
| `run(argv, local, sudo, timeout, check)` | I/O | inject `runner=subprocess.run` |
| `asterisk(cmd, local)` | I/O | inject runner via `run`; or inject `ast_fn` |
| `_is_asterisk_user()` | I/O | inject `uid_fn=os.geteuid` |
| `pdf_to_tiff(pdf, tif)` | I/O | inject `gs_fn=subprocess.run` |
| `tiff_pages(path)` | I/O (file read) | inject `open_fn` or pass bytes |
| `cmd_send(a)` | I/O | composed of I/O calls; thin orchestration |
| `wait_for(tif, local, seconds, before)` | I/O | inject `clock`, `sleep`, `ast_fn` |
| `cdr_rows(local, limit)` | I/O | inject `open_fn` / `runner` |
| `fax_rows(local, limit)` | **Pure** given rows | — (calls `cdr_rows` and `utc_to_local`) |
| `utc_to_local(s)` | I/O (env + zoneinfo) | inject `tz_name` and `now_fn` |
| `parse_stats(text)` | **Pure** | — |
| `cmd_status(a)` | I/O | composed; inject runner |
| `cmd_log(a)` | I/O | calls `fax_rows`; print side-effect |
| `cmd_test(a)` | I/O | delegates to `cmd_send` |
| `emit(a, obj, text)` | I/O (stdout) | inject `print_fn` |
| `main(argv)` | I/O | entry point; thin |

Pure functions ready to test without mocking: `norm_number`, `parse_stats`, and (given a list of
CDR rows) the filtering and enrichment logic inside `fax_rows`.

---

## 4. Shell-out inventory

`shell=True` does **not** appear anywhere in either program. Every `subprocess.run` call uses an
explicit list.

| Location | argv / command | Local or SSH | sudo | Timeout | Error handling | Failure visible as |
|---|---|---|---|---|---|---|
| `cli.py:56` (`run`) | arbitrary argv | local or `ssh -o BatchMode=yes pbx …` | optional `sudo -n` | 60 s default | `check=True` raises `SystemExit` | process exit |
| `cli.py:65` (`asterisk`) | `["asterisk", "-rx", cmd]` | local or via `run` | if not asterisk user | 60 s (via `run`) | `check=False`; returns `""` on error | empty string to caller |
| `cli.py:78–80` (`pdf_to_tiff`) | `["gs", "-q", …]` | local | no | 120 s | `check=True` raises `CalledProcessError` | process exit |
| `cli.py:114` (`cmd_send`) | `["scp", "-q", …]` | local (copies to pbx) | no | 60 s | `check=True` via `run` | `SystemExit` |
| `cli.py:115` (`cmd_send`) | `["install", "-o", "asterisk", …]` | on pbx via ssh | yes | 60 s | `check=True` via `run` | `SystemExit` |
| `cli.py:116` (`cmd_send`) | `["rm", "-f", …]` | on pbx via ssh | no | 60 s | `check=False` | silently ignored |
| `cli.py:231` (`cmd_status`) | `["which", "gs"]` | local or ssh | no | 60 s | `check=False` | `gs` field is `False` |
| `cli.py:140,144` (`wait_for`) | `"core show channels concise"`, `"fax show stats"` | via `asterisk()` | conditional | 60 s | returns `""` | empty stats dict / no break |
| `console:510–513` (`ast`) | `["asterisk", "-rx", cmd]` | local only (console runs on pbx) | no | 10 s | broad `except`; returns `None` | `None` → "not probed" |
| `console:2013–2014` (`fax_cli`) | `[FAX_CLI, "--local", "--json", *args]` | local | no | 40/90 s | `FileNotFoundError` and broad `except`; non-zero exit → error dict | `{"ok": False, "why": …}` |
| `console:419–424` (`_build_info`) | `["git", "rev-parse", …]`, `["git", "diff", …]` | local | no | 5 s | `OSError`/`SubprocessError` caught | falls back to `"dev"` |

Asterisk CLI commands issued by the CLI: `fax show stats`, `fax show sessions`,
`pjsip show endpoint voipms-fax`, `pjsip show registrations`, `pjsip show endpoint 2007`,
`module show like res_fax`, `core show channels concise`,
`channel originate PJSIP/<number>@voipms-fax application SendFax <path>,f`.

Asterisk CLI commands issued by the console: `pjsip show registrations`, `core show channels`,
`pjsip show endpoints` (plus elided cellular VTY calls).

---

## 5. Unsafe or fragile patterns

**5.1 `SystemExit` in library code — HIGH**
`norm_number` (cli:44) and `run` (cli:58) call `raise SystemExit(…)`. When the console calls
`fax_cli()`, a non-zero return code is caught (console:2021–2023), but a `SystemExit` raised
inside the subprocess is not observable from the parent — it only affects the child process. So
this is actually safe today, because the CLI always runs as a child. However, if the CLI is ever
imported as a module instead of shelled out, `norm_number` will terminate the console process.
Fix: replace `raise SystemExit(…)` with a proper exception (`ValueError`) and let `main()` catch
it and call `sys.exit`.

**5.2 Broad `except` clauses — MEDIUM**
`ast()` (console:513) catches bare `Exception` and returns `None`. This swallows timeouts,
permission errors, and Asterisk being absent identically. The result is always "not probed",
which is correct behaviour for the page but makes debugging harder. Also `tiff_pages` (cli:96)
swallows all exceptions and returns 0 pages — a silently wrong page count is worse than an
error. Fix: log the exception to stderr before returning the fallback.

**5.3 Number validation duplicated — HIGH (drift risk)**
`norm_number` in cli.py (lines 39–47) and the inline validation in `fax_send` (console:2060–2066)
both strip non-digits, normalise 10→11 digits, and block N11 numbers. They are not identical:
the CLI raises `SystemExit` on a bad number; the console returns `{"ok": False}`. Any future
change to the acceptable range must be made in both places. Fix: make the canonical validator
live in the CLI package and have the console call the CLI for even dry-run validation, or extract
the logic into a shared pure function.

**5.4 Uploaded PDF is never cleaned up — MEDIUM**
`fax_send` writes the PDF to `FAX_INBOX` (console:2078–2079) and never removes it. The TIFF
written by `pdf_to_tiff` during a send is also left in `SPOOL` (cli:110–116). For normal usage
the TIFF in SPOOL is intentional (Asterisk reads it), but the PDF copies accumulate. Fix: delete
the PDF after a successful send, or document the cleanup policy and add a cron/systemd timer.

**5.5 `utc_to_local` silently falls back to UTC — LOW**
If `zoneinfo` is unavailable or `FAX_TZ` names a non-existent zone, the function returns the raw
UTC string (cli:202–203). The console renders this without warning. Fix: catch `ZoneInfoNotFoundError`
specifically and emit a warning once at startup.

**5.6 Brittle text parsing of Asterisk output — HIGH**
`parse_stats` (cli:207–213) matches lines of the form `Key : 123`. `read_trunk` (console:1014–1020)
uses a regex that expects the exact column layout of `pjsip show registrations`. `cmd_status`
(cli:225–228) checks for the substring `"Registered"` in registration output and
`"Contact:.*voipms.*Avail"` in endpoint output. Any reformat from an Asterisk upgrade silently
returns wrong data. Fix: wrap each Asterisk read in a dedicated parser function and test it with
recorded fixtures.

**5.7 `wait_for` uses `time.sleep` in a tight loop — LOW**
`wait_for` (cli:138–143) calls `time.sleep(4)` then `time.sleep(3)` in a loop. This blocks the
CLI process, which is acceptable since the CLI is a CLI. It is not a problem today, but it becomes
one if `wait_for` is ever called from a request-handling thread. Fix: accept a `sleep_fn` parameter.

**5.8 Content-Length not checked before read — LOW (already mitigated)**
`do_POST` at console:2959 reads `Content-Length` and caps at `FAX_MAX_BYTES + 65536`. This is
correct. The `_multipart` parser uses `email.parser.BytesParser` on the already-read bytes, so
there is no streaming body issue. The pattern is fine.

**5.9 `fax_cli` discards all but the last line of stdout — MEDIUM**
`fax_cli` (console:2025) calls `.splitlines()[-1]` to parse the CLI's JSON. If the CLI emits a
warning or debug line before the JSON object, earlier lines are silently dropped. This is currently
safe because the CLI only prints JSON on stdout when `--json` is given, but it is fragile. Fix:
ensure the CLI writes only one JSON object to stdout, and parse the whole stdout rather than the
last line.

**5.10 `VoipMsPoller._refresh_once` has a broad `except` on the per-section loop — LOW (intended)**
The loop at console:945 catches bare `Exception` to keep the poller alive. This is correct for a
background poller (a failure on one section must not kill the thread), and the error is stored in
`self._data["error"]` and surfaced on the page. This pattern is fine.

**5.11 `snapshot()` creates a `ThreadPoolExecutor` on every request — MEDIUM**
`snapshot()` (console:1229) creates and tears down a `ThreadPoolExecutor(max_workers=7)` on
every `/api/state` request. With a 20 s auto-refresh this is ~3 threads/min per consumer. The
executor is bounded (7 workers), so threads do not accumulate, but the repeated create/teardown
adds overhead. Fix for modernization: a long-lived executor, or `asyncio`, is cleaner.

**5.12 Timezone-naive `datetime.now()` in `fax_send` — LOW**
`fax_send` (console:2077) uses `datetime.now()` (no timezone) to stamp the PDF filename. The
timestamp is local wall clock. Inconsistent with CDR timestamps which are UTC. Fix: use
`datetime.now(timezone.utc)` or make the stamp format explicit in a constant.

**5.13 No check that `Content-Type` boundary is present — LOW**
`_multipart` (console:2044) prepends the raw `Content-Type` header and lets `email.parser` split
on the boundary. If the browser omits the boundary token (malformed request), `email.parser`
returns an empty payload and `fax_send` returns `{"ok": False, "detail": "no PDF attached"}`.
This is safe; the error message is slightly misleading. Fine as-is.

---

## 6. JSON contracts

### `/api/fax` (GET) — `fax_state()` shape

```
{
  "ok":     bool,             # True if both CLI calls succeeded
  "status": {                 # the full status JSON from cli.py cmd_status
    "ok":                bool,
    "spandsp":           bool,
    "trunk_registered":  bool,
    "trunk_available":   bool,
    "obi100_registered": bool,
    "active_sessions":   [str, …],   # lines starting with "PJSIP"
    "stats":             {str: int, …},  # from fax show stats
    "gs":                bool
  },
  "log":    [{…row…}, …],    # up to 25 fax CDR rows (see below)
  "why":    str | None,       # first error from status or log
  "src":    str,              # descriptive string, not a URI
  "spool":  str,              # "/var/spool/asterisk/fax"
  "inbox":  str               # FAX_INBOX path
}
```

### Log row shape (from `fax_rows`)

```
{
  # raw CDR columns (18 total — see CDR_COLS at cli:29–31)
  "accountcode", "src", "dst", "dcontext", "clid", "channel", "dstchannel",
  "lastapp", "lastdata", "start", "answer", "end", "duration", "billsec",
  "disposition", "amaflags", "uniqueid", "userfield",
  # derived by fax_rows:
  "file":        str,          # TIFF filename extracted from lastdata, or ""
  "direction":   "in" | "out",
  "number":      str,          # normalised destination
  "start_local": str           # UTC→local, format "YYYY-MM-DD HH:MM"
}
```

**What the docs promise but the code omits**: AGENTS.md says `log` rows include `start_local,
direction, number, disposition, billsec, file`. The code produces all six, plus all 18 raw CDR
columns — the docs list is a minimum, not the full shape. No promised field is absent.

### `/api/fax/send` (POST) response — from `fax_send` → `cmd_send`

```
{
  "ok":         bool,
  "number":     str,           # 11-digit normalised
  "label":      str,
  "pages":      int,
  "tif":        str,           # absolute path in SPOOL
  "originate":  str,           # raw asterisk CLI output
  "started":    str,           # ISO 8601 (no timezone)
  "detail":     str,           # human message added by console
  "pdf":        str,           # absolute path in FAX_INBOX
  # if --wait was given (not used by console):
  "result": {
    "outcome":            "SENT" | "FAILED" | "UNKNOWN",
    "completed_delta":    int,
    "failed_delta":       int,
    # if a matching CDR row was found:
    "start", "answer", "end": str,
    "billsec":            str,
    "disposition":        str
  }
}
```

**Dry-run shape** (from cli:119 when `--dry-run` is set; the console never sets this):

```
{ "ok": true, "dry_run": true, "number": str, "pages": int, "tif": str }
```

**Discrepancy**: AGENTS.md lists `send --wait → {ok, number, pages, tif, result{outcome,…}}`.
The actual shape also contains `label`, `originate`, `started`, `detail`, and `pdf`. These are
additive and do not break the contract.

---

## 7. Test plan

### Pure functions to test first

| Function | Key edge cases |
|---|---|
| `norm_number` | 10-digit, 11-digit, leading 1, N11 prefixes (911, 988, …), non-digit chars, empty string, too short, too long |
| `parse_stats` | typical `fax show stats` output, empty string, lines with no colon, duplicate keys (first wins per `setdefault`) |
| `fax_rows` (filtering + enrichment) | `lastapp` = `SendFax`, `AppDial2` (should be filtered), `ReceiveFax`, `from-fax` context (number strip of leading 8/9), `dst == "s"` (number from TIFF name), `voipms-fax` in channel |

### Fixtures needed (one file per command output)

| Fixture file | Content |
|---|---|
| `tests/fixtures/fax_show_stats.txt` | Output of `fax show stats` with `Transmit Attempts: 3`, `Completed FAXes: 2`, `Failed FAXes: 1` |
| `tests/fixtures/fax_show_stats_empty.txt` | Empty output (no stats yet) |
| `tests/fixtures/fax_show_sessions_none.txt` | `0 active FAX sessions` header, no PJSIP lines |
| `tests/fixtures/fax_show_sessions_active.txt` | One `PJSIP/12025550142@voipms-fax` line |
| `tests/fixtures/pjsip_show_registrations_ok.txt` | `voipms-fax/sip:… Registered (exp. 3599s)` line |
| `tests/fixtures/pjsip_show_registrations_none.txt` | No registration rows |
| `tests/fixtures/pjsip_show_endpoint_voipms_avail.txt` | `Contact: …voipms… Avail` line |
| `tests/fixtures/pjsip_show_endpoint_obi_avail.txt` | `Contact: …2007@… Avail` line |
| `tests/fixtures/module_show_res_fax.txt` | `res_fax_spandsp.so` in output |
| `tests/fixtures/cdr_rows.csv` | Three CDR rows: one `SendFax` outbound to `12025550142`, one `AppDial2` stub leg, one `ReceiveFax` inbound from `12025550100` |

**Realistic but fictional CDR row** (one example):
```
,12025550142,s,from-internal,,PJSIP/2001-00000001,PJSIP/12025550142@voipms-fax-00000002,
SendFax,/var/spool/asterisk/fax/20260927-035801-FORM-1-12025550142.tif,
2026-09-27 10:58:01,2026-09-27 10:58:05,2026-09-27 10:58:43,42,38,ANSWERED,DOCUMENTATION,
1722080281.2,
```

### Edge cases each test must cover

- `parse_stats`: duplicate key — `setdefault` keeps the first value (cli:211).
- `fax_rows`: `AppDial2` rows are present in the input and must be absent from the output.
- `fax_rows`: `dst == "s"` path extracts number from TIFF filename; a TIFF with no number suffix should yield `"?"`.
- `norm_number`: all eight N11 codes (911, 988, 211, 311, 411, 511, 611, 711, 811) must be rejected.
- `norm_number`: a 10-digit number must have `"1"` prepended.

---

## 8. Migration order

### (a) CLI becomes a package with pure functions, dataclasses, and tests

Extract `norm_number`, `parse_stats`, and the enrichment/filtering logic from `fax_rows` into
`faxcli/parse.py` as plain functions with no I/O. Wrap each Asterisk call in a function that
accepts a `runner` parameter defaulting to `subprocess.run`. Define dataclasses for `StatusResult`,
`LogRow`, and `SendResult` matching the JSON shapes in §6. Replace `raise SystemExit` in library
functions with `ValueError`; let `main()` catch it.

**Risk**: changing `raise SystemExit` to `ValueError` is a behaviour change. If any caller expects
`SystemExit`, it will now see an unhandled `ValueError`. **Verify**: run `pytest -q` after each
function; confirm the CLI still exits non-zero on a bad number by running `fax send --dry-run`
with a malformed number.

### (b) One Asterisk adapter seam that can replay fixtures

Add `faxcli/asterisk.py` with a single function `run_ast(cmd) -> str` that calls `subprocess.run`
by default. Pass it as a parameter to every function that calls `asterisk()`. In tests, substitute
a fixture-backed implementation that reads from `tests/fixtures/*.txt` keyed by command string.
This seam isolates all text-parsing logic from process execution.

**Risk**: the seam must be injected consistently; a forgotten call site still spawns a process.
**Verify**: run the test suite with a fake runner that raises `AssertionError` on any real
`subprocess` call; every test that doesn't mock the runner explicitly should fail if it reaches
`subprocess`.

### (c) Fax panel extracted into a small service with a typed API and a replay mode

Create `faxconsole/` with a FastAPI (or stdlib `http.server`) service that exposes
`GET /api/fax` and `POST /api/fax/send`. Under a `--replay` flag, all Asterisk and CLI calls are
replaced by fixture-backed stubs. The `fax_state()` and `fax_send()` equivalents call the typed
dataclasses from step (a) instead of parsing raw dicts. Write auth stays as-is (token in env,
`hmac.compare_digest`).

**Risk**: the console's `/api/fax` route must keep returning the same JSON shape. **Verify**: add
a contract test that loads `tests/fixtures/fax_state_response.json` and asserts every field in
§6 is present with the right type.

### (d) Inbound-fax design as generated config and tests only — never deployed

Implement `faxcli/inbound.py` with a `render_dialplan(config) -> str` function that generates the
`[from-fax-did]` block from `legacy/fax/docs/inbound.md` (Option A, lines 27–38). Write tests
that assert the rendered output is parseable as Asterisk dialplan syntax (check for `exten =>`,
`ReceiveFax`, the `f` option, and the `h` extension for the hook). No subprocess call, no PBX
write.

**Risk**: a generated config that looks right but is syntactically wrong (e.g. missing comma in
`exten => _X.,1,…`) would break the dialplan silently on deployment. **Verify**: run the generated
text through `asterisk -T` (syntax check, no daemon) in CI using a recorded fixture of what a
passing check looks like. Mark the test `@pytest.mark.skipif(shutil.which("asterisk") is None, …)`
so it only runs on the PBX.

---

## 9. Review of this analysis

*Everything above §9 is Bob's text, unedited (run 1: `docs/bob-runs/1-analysis.*`). The
orchestrating agent (Claude) wrote this section after checking Bob's claims against the code.
"Demonstrated" means the behaviour was reproduced by importing the frozen legacy CLI with a
fake transport; nothing was sent or dialled.*

**Verified.**
- The line citations in the module map, the request flows, §4 and §5: spot-checked against
  the file, and all match except the one noted below.
- `shell=True`: absent, 0 hits in `legacy/`.
- The JSON shapes in §6, including that the console's `send` never passes `--wait` and so
  never receives `result`.
- The duplicated validation (§5.3), the uploads that are never removed (§5.4), the
  last-line JSON parse (§5.9) and the per-request executor (§5.11).
- Bob also found the realm-sigil `git` shell-outs (console:419–424), which were not asked for.

**Corrected or rejected.**
1. §1, finding 2 overstates "every I/O call raises `SystemExit`". Only `norm_number` and
   `run(check=True)` do (cli.py:44, 58). `asterisk()` returns `""` (cli.py:66), and `pdf_to_tiff`
   raises `CalledProcessError` (cli.py:78–80), as Bob's own §4 table says. The severity in §5.1
   applies to the migration, where the CLI becomes an importable library, not to production today.
2. §5.9 says the CLI prints only JSON under `--json`. Not so: `fax test` prints a banner line
   first, even with `--json` (cli.py:259). The console's last-line parse (console:2025) is
   therefore load-bearing today, not just fragile.
3. §5.8's "the pattern is fine" holds only in part. A negative `Content-Length` makes
   `self.rfile.read(n)` (console:2966) read until EOF, and a non-numeric one raises an unhandled
   `ValueError` (console:2959). Both sit behind the write token (console:2956), so: LOW.
4. §8(c), FastAPI: **rejected.** AGENTS.md says stdlib only at runtime, because the PBX host has
   no pip. The service will use stdlib `http.server`.
5. §8(d), `asterisk -T` as a syntax check: **rejected, it is wrong.** `-T` adds timestamps to
   CLI output, and Asterisk has no offline dialplan checker. The generated config is verified by
   structural tests only and is never loaded into a PBX.
6. §7 says "all eight N11 codes (911, 988, …)". The list has nine codes, and 988 (the crisis
   line) is not N11. Tests will cover all nine.
7. §2 table: `ast()` is at console:507–514, not inside 1009–1136.

**Added: findings the analysis missed.**
- **A. HIGH — an unreadable PBX is reported as `ok: true`.** `asterisk()` turns every failure
  into `""` (cli.py:62–66), and `cmd_status` sets `"ok": True` unconditionally (cli.py:224).
  Demonstrated: all 7 transport calls failed (exit 255), yet `fax --json status` printed
  `{"ok": true, "spandsp": false, "trunk_registered": false, …}`. The console turns that into
  confident red tiles, breaking its own rule, "NEVER RENDER A STATE YOU CANNOT ACTUALLY READ"
  (console:24). The remote CDR read fails the same way (cli.py:164): the log says "no fax
  calls". Fix: the Asterisk seam must tell "read, and empty" apart from "could not read", and
  `status` must say which reads failed. This one fix protects the core function.
- **B. MEDIUM.** `run()` does not catch `subprocess.TimeoutExpired` (cli.py:56). A hung ssh or
  Asterisk CLI crashes the CLI with a traceback instead of a clean error.
- **C. LOW, dead code.** The VoIP.ms panel warns "VoIP.ms and asterisk disagree" when
  `v.agrees_with_asterisk === false` (console:1706). But `VoipMsPoller.snapshot()`
  (console:977–1003) never sets that field, and `/api/voipms` returns the snapshot unchanged
  (console:2859–2861). The cross-check can never fire.
- **D. LOW, already handled.** VoIP.ms credentials travel in the query string (console:847–848)
  because that API requires it, over HTTPS. Every error path passes through `_voipms_scrub`
  (console:681) and uses `from None`. Keep both when porting.
- **E. LOW.** `CDR_COLS` is defined twice (cli.py:29–31, console:1144–1147): the same drift
  risk as §5.3.
- **F. MEDIUM.** `ThreadingHTTPServer` (console:2981) starts one thread per request with no cap,
  and each `/api/state` request adds `snapshot()`'s 7-worker executor. Each request is bounded,
  but the total is not.

**What changes in the plan as a result.** Step (a) adds a `Reading` result type
(`ok | failed(why)`) at the Asterisk seam. It also adds characterization tests that run the
frozen legacy functions and the new ones on the same fixtures, so "without disrupting the core
function" is checked, not assumed. Finding A becomes the first behaviour change, and it is
deliberate: a status that could not be read reports `ok: false`.
