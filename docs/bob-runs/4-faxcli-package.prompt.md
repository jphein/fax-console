Step (a) of the migration in `docs/analysis.md` §8: turn the legacy fax CLI into a typed, tested package, `faxcli/`. Read `AGENTS.md` first, then `docs/analysis.md`. Read §9 carefully; it corrects §1–§8. Also read `legacy/fax/fax/cli.py` and `tests/fixtures/README.md`. Never edit anything under `legacy/`.

**Goal.** Same behaviour as `legacy/fax/fax/cli.py`, now split into pure functions and thin I/O. There is one deliberate exception (§9, finding A).

Package layout. You may adjust names, but keep the split:
- `faxcli/numbers.py`: `normalize(s) -> str` and an `InvalidNumber(ValueError)` exception. It must never exit the process. The blocked 3-digit codes are the legacy nine.
- `faxcli/asterisk.py`: pure parsers over Asterisk CLI text:
  - `parse_stats`. The FIRST occurrence of a key wins, exactly as the legacy `setdefault`.
  - the sessions list;
  - trunk registered;
  - a contact is available for an AOR;
  - a module is loaded;
  - the trunk still has a channel up.
- `faxcli/cdr.py`: the CDR columns, parsing `Master.csv` text into records, the fax-log derivation, and `utc_to_local(s, tz)` with the time zone passed in. The fax-log derivation is the legacy `fax_rows` logic, which covers:
  - the filter;
  - `AppDial2` stub legs;
  - the 8/9 prefix strip for `from-fax`;
  - the number taken from the TIFF name when `dst == "s"`, or `?`;
  - direction and `start_local`;
  - newest first.
- `faxcli/outcome.py`: judge a send from the before and after `fax show stats` counters (SENT / FAILED / UNKNOWN, plus deltas).
- `faxcli/tiff.py`: count TIFF pages from bytes, with no libtiff.
- `faxcli/models.py`: frozen dataclasses for the JSON shapes (status, log row, send job, dry run, send result). Each has a `to_json()` that returns exactly the legacy keys in the legacy order, and it may add keys.
- `faxcli/transport.py`: the one I/O seam (the recorded fixtures are in `tests/fixtures/asterisk/` and `tests/fixtures/cdr/`).
  - A `Reading(ok, text, why)` result, so "read, and empty" is distinguishable from "could not read".
  - A `Transport` protocol with a local implementation and an ssh implementation (`-o BatchMode=yes -o ConnectTimeout=8`, `sudo -n`). Both catch `TimeoutExpired`.
  - A `ReplayTransport` that serves `tests/fixtures/asterisk/<command_with_underscores>.txt` and `tests/fixtures/cdr/Master.csv`. It also serves failures on request.
- `faxcli/cli.py`: argparse with the same subcommands and flags, and the same text and `--json` output. Signature: `main(argv=None, transport=None, stdout=None) -> int`. `faxcli/__main__.py`. A `fax` console script in `pyproject.toml`.

**The deliberate behaviour change.** When any status read fails, `status` must report:
- `"ok": false`;
- a `"why"` naming the commands that could not be read;
- an additive `"unread": [...]` list.

It must never report `ok: true` with made-up false values. The console already shows its "could not be read" banner when `ok` is false. Pin this change in the tests.

**Tests.** pytest, in `tests/`. Target 45 or more product tests. `tests/test_sandbox_guard.py` exists and is not yours, so do not count or change it. You run inside an OS sandbox, so your test runs are sandboxed too. Three kinds are required:
1. **Unit tests** of every pure function, on the recorded fixtures plus small inline cases. Cover:
   - all nine blocked codes, 10 and 11 digits, punctuation, too short or too long;
   - first-wins `Success` in `parse_stats`;
   - `AppDial2` excluded; the `?` number case; the MX922 prefix strip;
   - UTC→`America/Los_Angeles` across the date line;
   - multi-page TIFFs in both byte orders, built in memory;
   - SENT / FAILED / UNKNOWN.
2. **Golden tests.** `tests/fixtures/golden/status.json` and `log.json` are what the real CLI printed against the real PBX (see `tests/fixtures/README.md`). Your `main(["--json", "status"])` and `main(["--json", "log", "--limit", "400"])`, driven by `ReplayTransport` over the recorded fixtures, must print exactly those objects.
3. **Characterization tests** that import the frozen legacy module read-only (`importlib.util.spec_from_file_location("legacy_cli", "legacy/fax/fax/cli.py")`) and assert that legacy and new agree on the same inputs:
   - `norm_number` against `normalize` over a corpus, including that both reject the same inputs;
   - `parse_stats` and `utc_to_local` on the fixtures;
   - `fax_rows` (with its `cdr_rows` replaced to serve the fixture) against your fax log, row by row;
   - the whole `status`, `log` and `send --dry-run` JSON. Drive legacy `main` with its module-level `subprocess.run` replaced by a fake that serves the fixtures, and drive yours with `ReplayTransport`. The only allowed difference is the deliberate one above, and it gets its own test.

No test may spawn a real process. Add a fixture (in `tests/conftest.py`) that makes `subprocess.run` and `os.system` raise if a test reaches them unexpectedly.

**Tooling.**
- `pyproject.toml`: setuptools, `requires-python >= 3.10`, license AGPL-3.0-or-later, no runtime dependencies.
- ruff config: line length 110, rules E, F, W, I, B, UP, SIM.
- `[tool.pytest.ini_options] testpaths = ["tests"]`.
- Run the tests with `.venv/bin/python -m pytest -q` and lint with `.venv/bin/ruff check .`. Both must pass before you finish.
- Do not run the CLI itself; the guard refuses that. Do not install anything.

Finish with a short summary: the files written, the test count, and any legacy behaviour you found surprising, with its line number.
