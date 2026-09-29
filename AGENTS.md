# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## What this repository is
The modernization of a working house-PBX fax service. The legacy code is in `legacy/`.
It has two parts: a Python fax CLI around Asterisk `SendFax`, and an excerpt of a
single-file stdlib web console, containing its Fax panel plus the Asterisk/VoIP.ms status
code. Read `BASELINE.md` before touching anything.

## Hard rules (a hook enforces each one; a refusal is expected, not a bug)
1. **`legacy/` is frozen.** Read it, analyse it, quote it. Never edit it. New code goes in
   `faxcli/` (the CLI package) and later `faxconsole/`.
2. **Never reach a network, a PBX or anything outside this repository.** That rules out
   ssh, scp, curl, gh, git push, pip install, sudo, asterisk, and running the legacy code
   or the `fax` CLI for real. The legacy code shells out to `ssh pbx …`, and running it
   would try to dial. Exercise behaviour through **pytest with mocked I/O and recorded
   fixtures** only.
3. **No identifying data, ever.** Phone numbers must be in the fictional `555-0100`…`555-0199`
   block (e.g. `202-555-0142`). The public test receivers Faxbeep (`1-972-532-9272`) and HP
   are the only exceptions. IP addresses must be in `192.0.2.0/24` or loopback. Hostnames
   must be `pbx` or `*.example.com`. No person names. `scripts/scrub-check.sh` gates every
   write and every commit.
4. **Keep the JSON contracts stable.** The console consumes the CLI's `--json` output:
   - `status` → `{ok, spandsp, trunk_registered, trunk_available, obi100_registered, active_sessions[], stats{}, gs}`
   - `log` → `{ok, rows[]}`. Each row has `start_local, direction, number, disposition, billsec, file` plus the raw CDR columns.
   - `send --wait` → `{ok, number, pages, tif, result{outcome, …}}`
   - `send --dry-run` → `{ok, dry_run, number, pages, tif}`

   A refactor may add fields. It must not rename or remove any.
5. **Measured facts in the legacy docs stay true.** A CDR `ANSWERED` is not a delivered fax.
   Only the `fax show stats` counter deltas are. `SendFax` needs the `f` option, because
   VoIP.ms refuses T.38. Asterisk CLI `originate` separates the app and its args with a space.

## Where Bob runs
Bob runs inside `scripts/bob-sandbox.sh`, an OS sandbox, and that is the security boundary:
- a filesystem view of this repo only, with `legacy/`, `.git/`, `.bob/`, `scripts/`, `.github/`,
  `.venv/`, this file and the run evidence (`docs/bob-usage.md`, `docs/bob-runs/`) read-only;
- no network path to the LAN or loopback;
- a clean home directory.

The hooks in `.bob/` are an audit and early-warning layer inside it. **Bob's skills
directories stay empty:** Bob lists every skill it can find in its prompt, so none from outside
this project may be visible to it. Code you write here (tests, `conftest.py`) runs in the
sandbox or in CI.

## Conventions
- Python ≥ 3.10, stdlib only at runtime (the PBX host has no pip). Dev tools: pytest, ruff.
- Pure functions (parsing, normalising, judging outcomes) stay separate from I/O
  (subprocess, ssh, files, clock). I/O goes behind small injectable seams, so tests never
  spawn a process.
- Tests live in `tests/`, fixtures in `tests/fixtures/`, one fixture per recorded command
  output. Inside the sandbox (as Bob): `.venv/bin/python -m pytest -q` and `.venv/bin/ruff check .`.
  **On the workstation, only `scripts/test.sh`**, which runs both inside the sandbox. A test
  suite executes whatever it contains, so agent-written tests never run unsandboxed there. CI runs
  them on GitHub's disposable runners, which have no secrets and no route to the house network.
- Docs go in `docs/`. Write plainly and cite the file and line you are describing.
