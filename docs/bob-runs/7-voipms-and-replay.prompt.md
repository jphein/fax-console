Week 2, run 7. First fix what the review of your run 6 found; then port the VoIP.ms poller. Read `AGENTS.md`, `docs/console-slice.md` and `docs/plan-week2.md` first. Never edit `legacy/` or `tests/test_sandbox_guard.py`. All existing tests must stay green, including the faxcli goldens and characterization tests.

**Part 1: the review of run 6.**
1. **Replay mode must never touch a real path.** `python3 -m faxconsole --replay DIR` builds `ReplayTransport` without `spool_dir`, so a replay dry run renders into the real spool path, and uploads land in a permanent inbox.
   - In replay mode, create one temporary directory (`tempfile.mkdtemp`), and use it for both the spool and the inbox. Remove it on shutdown.
   - Make `Config(replay=True)` refuse any transport that isn't a `ReplayTransport`, raising at construction.
   - Test: a replay send writes only under that temp dir; nothing appears under `/var`.
2. **`--ssh` with no host** must use `FAX_EXCHANGE_HOST`, with `pbx` as the default. Do this by passing `host=None` (see `faxcli.transport.exchange_host`). The const `"pbx"` currently overrides the environment.
3. **A typed send API.** `faxconsole` still calls `cli.cmd_send` with an `argparse.Namespace` and parses the JSON that it prints. That is the shell-out with the process removed.
   - Add `faxcli.api.send(pdf, number, *, label=None, dry_run=False, wait=0, transport)`. It returns the `DryRunResult` / `SendResult` dataclass, or raises typed errors (`InvalidNumber`, and a new `SendError` with a reason).
   - `cmd_send` becomes a thin printer over it. Its printed JSON must not change: the characterization tests prove it.
   - `faxconsole` calls the API directly.
4. **A bounded queue.** The server's pool has 8 workers but an unbounded queue. Cap the waiting requests (for example, a bounded semaphore sized to the pool plus a small backlog). A request over the cap gets a `503` with a JSON body and `Retry-After`. Test this without TCP.

**Part 2: the VoIP.ms poller** (`faxconsole/voipms.py`, from `VoipMsPoller`, e:760–1003; `_voipms_scrub`, e:681–712; `_voipms_creds`, e:715–757).
- Keep every legacy rule in its comments:
  - credentials never reach an error string, and error paths are scrubbed with `from None`;
  - the credentials file is read line by line, keeping only the three keys;
  - the cache is written atomically;
  - `None` means "not measured", not zero;
  - the snapshot never blocks;
  - no API call happens on a request path.
- Make its I/O injectable: an `http(method, params) -> dict` callable, a clock, `sleep`, the cache path and the credentials path. Add a `stop()`; legacy had none.
- **Replay:** a fixture HTTP that serves `tests/fixtures/voipms/{getBalance,getRegistrationStatus,getDIDsInfo}.json`. **Synthesize these fixtures** from the fields the legacy code reads (never capture real responses). Use fictional values only:
  - the DID `202-555-0100`;
  - the server `pop1.example.com`;
  - the register IP `192.0.2.20`;
  - the sub-account `000000_house`.

  Add a README line in `tests/fixtures/voipms/` saying the fixtures are synthesized.
- The `GET /api/voipms` route returns the snapshot. In replay mode the poller runs on the fixture HTTP and never uses the network.
- **Characterization:** import the frozen legacy console read-only, with a refusing fake `subprocess.run` installed before the import (see `tests/test_faxconsole_pbx.py`). Feed the legacy `VoipMsPoller` and yours the same fixture responses and the same fixed clock. Assert that `snapshot()` agrees field by field, including `age`, `stale`, `balance_low`, `months_left` and `days_to_billing`.
- A test credentials file must be assembled at runtime. The scrub gate refuses a literal `VOIPMS_PASS=…` or `api_password=…` assignment in any file, test files included (see the `j()` helper in `tests/test_sandbox_guard.py`).
- Tests may not open a socket or reach a network. The real HTTP client exists only for live mode, and no test runs it.

`.venv/bin/python -m pytest -q` must show 0 failures, and `.venv/bin/ruff check .` must be clean. **Before you run out of budget, stop and give a short summary**: what changed for each numbered item, the test count before and after, and anything you disagree with in this review, with the reason. The last three runs ended at their cap without one.
