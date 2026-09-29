# Deliberate behaviour changes

Every entry here records a case where `faxcli` consciously diverges from
`legacy/fax/fax/cli.py`.  The format is:

- **Legacy**: what the frozen code did.
- **faxcli**: what the new code does.
- **Why**: the reason for the change.
- **Tests**: characterization test (runs legacy, pins the old behaviour) and
  behaviour test (pins the new behaviour).

---

## Finding A — unreadable PBX reports `ok: false`

Introduced: run 8 (docs/bob-runs/).

**Legacy** (`legacy/fax/fax/cli.py:216–237`): `cmd_status` calls `asterisk()`
for each reading.  `asterisk()` returns `""` on any failure (`cli.py:66`).
`cmd_status` sets `"ok": True` unconditionally (`cli.py:224`), so a PBX that
cannot be reached is reported as healthy with zeroed fields.

**faxcli** (`faxcli/cli.py:45–113`, `faxcli/transport.py`): each transport
read returns a `Reading(ok, text, why)`.  When any read fails, `cmd_status`
sets `ok: False` and includes `why` and `unread` in the JSON.

**Why**: the console's own comment says "NEVER RENDER A STATE YOU CANNOT
ACTUALLY READ" (`legacy/console/telephony-console.py:24`).  Reporting `ok:
true` when no read succeeded directly contradicts this.

**Tests**: `tests/test_characterization.py::TestDeliberateDifference`
(characterization: `test_legacy_ok_true_on_failure`; new:
`test_new_ok_false_on_failure`).

---

## Item 1 — failed originate raises `SendError` (run 12)

**Legacy** (`legacy/fax/fax/cli.py:121–130`): `out = asterisk(cli, local)`.
`asterisk()` returns `""` when the command exits non-zero (`cli.py:66`).  The
job dict is built unconditionally with `"ok": True`, so a failed originate is
silently reported as a successful send.

**faxcli** (`faxcli/api.py`): after the originate call, `originate_reading.ok`
is checked.  If False, `SendError` is raised with `originate_reading.why`.
`cmd_send` catches `SendError`, prints the reason to stderr, and returns exit
code 1.  A successful send's JSON shape is unchanged.

**Why**: a failed originate means no call was placed.  Reporting `ok: true`
misleads the operator into thinking a fax is in flight.

**Tests**: `tests/test_run12.py::TestFailedOriginate`
- characterization: `test_legacy_ok_true_on_failed_originate`
- new: `test_new_raises_send_error_on_failed_originate`,
  `test_new_send_error_carries_why`, `test_successful_send_json_unchanged`

---

## Item 2 — failed "before" stats read marks outcome as UNMEASURED (run 12)

**Legacy** (`legacy/fax/fax/cli.py:145–148`): `wait_for` calls
`parse_stats(asterisk("fax show stats", local))`.  When the read fails,
`asterisk()` returns `""` and `parse_stats("")` returns `{}`.  The delta is
then `after.get(k, 0) - {}.get(k, 0)` = `after.get(k, 0)`, so all previous
fax completions on the PBX appear to belong to this one send.

**faxcli** (`faxcli/api.py`, `faxcli/outcome.py`): `before_reading.ok` is
checked.  If False, `before_ok=False` is passed to `outcome.judge()`.  `judge`
returns `{"outcome": "UNMEASURED", "completed_delta": None, "failed_delta":
None}` instead of computing a delta from an absent baseline.

**Why**: a delta measured from zero is not a measurement — it claims to know
something the PBX never told us.  `UNMEASURED` is honest; `SENT` or `FAILED`
derived from zero would be a fabricated result.

**Tests**: `tests/test_run12.py::TestFailedBeforeStats`
- characterization: `test_legacy_counts_from_zero_on_failed_before`
- new: `test_new_unmeasured_when_before_fails`,
  `test_new_unmeasured_when_after_fails`, `test_new_measured_when_both_ok`,
  `test_wait_result_unmeasured_when_before_stats_fails`

---

## Item 3 — empty CDR `file` field matches nothing (run 12)

**Legacy** (`legacy/fax/fax/cli.py:150`):
```python
if tif.endswith(row.get("file", "\0")):
```
When `row["file"]` is `""` (no TIFF path found in `lastdata`), this becomes
`tif.endswith("")` which is always `True` in Python.  The first such row is
incorrectly attached to the send result.

**faxcli** (`faxcli/api.py`): the match is guarded:
```python
file_field = row.get("file", "")
if file_field and effective_tif.endswith(file_field):
```
An empty `file_field` is falsy and never matched.

**Why**: matching every TIFF path against an empty string is clearly wrong.
CDR rows with no TIFF path (`lastdata` contained no `*.tif`/`*.tiff`) should
not be attached to any send.

**Tests**: `tests/test_run12.py::TestEmptyCdrFileField`
- characterization: `test_legacy_empty_file_matches_every_tif`
- new: `test_new_empty_file_does_not_match`, `test_new_nonempty_file_still_matches`

---

## Item 4a — non-local render uses `tempfile.mkdtemp` (run 12)

**Legacy** (`legacy/fax/fax/cli.py:110`):
```python
localtif = os.path.join("/tmp" if not local else SPOOL, name)
```
The path is `/tmp/<timestamp>-<label>-<number>.tif`.  Another local user can
predict this path and pre-create a file or symlink at it before the render.

**faxcli** (`faxcli/api.py`): when `local=False`, a directory is created with
`tempfile.mkdtemp()`, which uses a mode-0700 directory with an unpredictable
name.  The TIFF is written inside it.  The directory is removed with
`shutil.rmtree` in a `finally`, so it goes on every path: after spooling, on a spool error, on a failed
render, and on an unreadable TIFF. (Review of run 12: the first version cleaned up only on the spool paths,
so a failed render left the directory behind.)

**Why**: `/tmp/<predictable-name>` is a classic TOCTOU / symlink-attack target.
`tempfile.mkdtemp` is the stdlib-recommended fix.

**Tests**: `tests/test_run12.py::TestTempfileForNonLocalRender`
- `test_render_path_is_not_predictable_slash_tmp`
- `test_tmpdir_cleaned_up_after_dry_run`
- review: `TestReviewOfRun12::test_a_failed_render_leaves_no_temp_dir`

---

## Item 4b — `--` before host in `SshTransport` (run 12)

**Legacy** (`legacy/fax/fax/cli.py:55`):
```python
argv = SSH + [EXCHANGE, " ".join(shlex.quote(a) for a in argv)]
```
`SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]`.  If
`FAX_EXCHANGE_HOST` is set to a value starting with `-`, it is passed directly
to `ssh` as a positional argument after the options, where ssh may interpret it
as another option flag.

**faxcli** (`faxcli/transport.py`): `_ssh` now builds:
```python
full = ["ssh"] + SSH_OPTS + ["--", self.host, remote_cmd]
```
`--` signals the end of options to ssh, so any host that starts with `-` is
treated as the hostname, not an option.

**Why**: hosts come from `FAX_EXCHANGE_HOST` (an env var), which an operator
could accidentally set to a value starting with `-`.  The fix costs one token
in the argv and closes the injection surface.

**Tests**: `tests/test_run12.py::TestSshDashDashBeforeHost`
- characterization: `test_dash_dash_legacy_did_not_have_it`,
  `test_dash_host_becomes_option_in_legacy_argv`
- new: `test_dash_dash_before_host`, `test_new_argv_with_dash_host_has_guard`

Also pins in: `tests/test_transport.py` (the existing argv tests now see `--`
in the argv; they did not assert its absence, so they continue to pass).

---

## Item 4c — `LocalTransport.read_cdr` honours `limit` (run 12)

**Legacy** (`legacy/fax/fax/cli.py:156–170`): `cdr_rows(local=True, limit=N)`
reads the entire CDR file with `open(CDR)` and then slices `rows[-N:]`.  The
full file is always read regardless of `N`.

**faxcli** (`faxcli/transport.py`): `LocalTransport.read_cdr(limit)` streams the
file through a `collections.deque(maxlen=limit)`, so it keeps only the last `limit` lines in memory, and
returns those. A limit of 0 or less returns nothing, as `tail -n 0` does. The text passed to `parse_cdr` is
therefore bounded, consistent with the SSH transport, which passes `tail -n limit` to the remote host.
(Review of run 12: the first version read every line and sliced `lines[-limit:]`. That still held the
whole file in memory, and for `limit=0` it returned every line, because `lines[-0:]` is the whole list.)

**Why**: the SSH and local transports now behave symmetrically.  On a very long
CDR (years of call records), the local path was always reading the whole file
into memory while the SSH path was bounded.

**Tests**: `tests/test_run12.py::TestLocalReadCdrLimit`
- characterization: `test_legacy_reads_whole_file_ignoring_limit`
- new: `test_new_read_cdr_honours_limit`,
  `test_new_read_cdr_limit_larger_than_file`
- review: `TestReviewOfRun12::test_read_cdr_limit_zero_is_nothing_and_a_limit_is_the_tail`

---

## Item 6: a log limit of 0 or less returns no rows (review of PR 8)

**Legacy** (`legacy/fax/fax/cli.py:167`): `rows[-limit:]`. For `limit=0` that is `rows[-0:]`, which is
every row.

**faxcli** (`faxcli/cdr.py`): `parse_cdr` returns no rows for a limit of 0 or less, as `tail -n 0` does.
The replay transport now agrees with the local and ssh ones, which already returned nothing. The
console's route also clamps its `limit` to 1..1000 (run 13).

**Tests**: `tests/test_review_run13.py::test_a_limit_of_zero_or_less_is_no_rows_whichever_transport_read_the_text`

