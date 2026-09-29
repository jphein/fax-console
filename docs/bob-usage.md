# How IBM Bob was used

This file records every Bob run on this project: the prompt, what Bob produced, what was
kept, what was changed or rejected and why, and what it cost. It is the evidence for "Bob as
a core part of the workflow". Each run's raw record is kept under
[`docs/bob-runs/`](bob-runs/). The records are verbatim except for two mechanical rewrites
made before publishing: the absolute repo path became `.`, and two cellular endpoint names
match the rebuilt baseline.

| File | Contents |
|---|---|
| `N-slug.prompt.md` | The exact prompt, scrub-checked before it was sent. |
| `N-slug.jsonl` | Bob Shell's `stream-json` output, verbatim: every message, tool call and result. |
| `N-slug.guard.jsonl` | Every allow or deny decision the sandbox hooks made during the run. |

## How Bob is driven
- **Bob Shell 2.0.5, headless:**
  `bob run --format stream-json --max-cost N --disable-tool-groups skill,mcp,browser,mode`,
  wrapped by [`scripts/bob-run.sh`](../scripts/bob-run.sh). It runs in a terminal the owner
  can watch; [`scripts/bob-watch.py`](../scripts/bob-watch.py) renders the stream readably.
  `BOB_TMUX=1` runs it in tmux session `bob` instead, so an agent's tool timeout cannot cut a
  run short.
- **Bob follows the repo's own rules.** [`AGENTS.md`](../AGENTS.md) holds them: the frozen
  baseline, no network or PBX access, fictional data only, and stable JSON contracts.
- **The security boundary is an OS sandbox**, [`scripts/bob-sandbox.sh`](../scripts/bob-sandbox.sh).
  Bob's whole process tree runs inside it, including any tests Bob writes and runs:
  - **Filesystem (bubblewrap):** Bob sees this repo and nothing else of the workstation.
    `legacy/`, `.git/`, `.bob/`, `scripts/`, `.github/`, `.venv/` and `AGENTS.md` are
    read-only, and so is the evidence: this file and `docs/bob-runs/`, and `docs/` itself
    cannot be renamed. `bob-run.sh` records Bob's stream outside the repository while Bob runs,
    finalizes the ledger from that copy, and publishes it in `docs/bob-runs/` only after the
    sandbox has exited and `docs/` is proven to be the same directory. Bob gets a clean home
    directory and a minimal `/etc`, with no hosts file and no ssh config.
  - **Network (a systemd scope with BPF address filters):** the LAN, loopback, link-local and
    CGNAT ranges are denied, so the PBX and every house service are unreachable. The public
    internet stays open for Bob's own API.
  - **Processes:** Bob gets its own PID, IPC and UTS namespaces, and a new session.
  - [`scripts/sandbox-probe.sh`](../scripts/sandbox-probe.sh) proves the containment with
    38 probes. One is a live positive control: ssh to the real PBX succeeds outside the
    sandbox and fails inside it, under every trick tried.
- **The clean home directory is load-bearing.** Bob Shell lists every skill it finds under
  `~/.bob`, `~/.agents` and `~/.claude` (including their `plugins/*/skills`) in its system
  prompt, names and descriptions included, even with the `skill` tool group disabled. On a
  workstation, those skills belong to other projects. Run 3 confirms that only Bob's six
  built-in skills are listed now.
- **The workspace hooks are audit and early warning, not the boundary**
  ([`.bob/settings.json`](../.bob/settings.json)):
  - [`prompt_gate.py`](../.bob/hooks/prompt_gate.py) scrub-checks every prompt (rules §8.6).
    The wrapper also checks each prompt with the private deny-list before sending it.
  - [`tool_guard.py`](../.bob/hooks/tool_guard.py) refuses risky commands and writes early,
    so Bob hears a clear reason, and it logs every decision.
  - An independent review showed that a regex over a shell command can be evaded (quoting,
    absolute paths, `python -c`). That is why the OS sandbox exists.
  - [`tests/test_sandbox_guard.py`](../tests/test_sandbox_guard.py) has 56 cases.
- **The orchestrating agent (Claude) reviews everything Bob writes.** It checks claims against
  the code and records corrections here. Nothing Bob writes is committed unread.
- **Commits whose content Bob wrote carry an `Assisted-by: IBM Bob` trailer**, so
  `git log --grep "Assisted-by: IBM Bob"` lists them.

## Ledger
Costs are Bob Shell's `session_costs`, the Bobcoin figure; the wrapper fills them in (see **Budget** below).

| # | Date (PDT) | Task | Bob's output | Tool calls | Cost | Kept / changed |
|---|---|---|---|---|---|---|
| – | 9/28 21:30 | Setup check ("reply ok") | one word | 0 | 0.027 | — |
| 0 | 9/28 22:13 | [Sandbox smoke test](bob-runs/0-sandbox-smoke.prompt.md) | one file written; `curl` refused; an outside path refused | 3 | 0.083 | Proved the hooks fire in headless mode and that Bob reports refusals accurately |
| 1 | 9/28 22:15 | [Modernization analysis](bob-runs/1-analysis.prompt.md) | [`docs/analysis.md`](analysis.md) §1–§8, 451 lines | 26 | 3.078 | Kept verbatim; 7 corrections and 6 added findings in §9 |
| – | 9/28 22:19 | [Budget-wrapper smoke test](bob-runs/drift-smoke.prompt.md) ("reply OK", ask mode, empty workspace; pre-sandbox, real HOME) | one word ([stream](bob-runs/drift-smoke.jsonl)) | 0 | 0.016 | Proved the Bobcoin gate, the stream log and the ledger update before they touched this file |
| 2 | 9/28 22:34 | [Isolation check](bob-runs/2-isolation-check.prompt.md) | none: the prompt gate refused the prompt, failing closed, because the private deny-list was not reachable from the clean home | 0 | 0 | Showed the gate fails closed; led to the sandbox's split between generic rules inside and the private list outside |
| 3 | 9/28 22:44 | [Sandbox check](bob-runs/3-sandbox-check.prompt.md) | "ok", from inside the OS sandbox | 0 | 0.021 | Proved Bob works sandboxed; its prompt now lists only Bob's own six skills |
| 4 | 9/28 23:02 | [The faxcli package](bob-runs/4-faxcli-package.prompt.md) | `faxcli/` (9 modules, ~905 lines), `pyproject.toml`, 121 tests (unit, golden, characterization) | 58 | 6.027 | Architecture kept. Review found 2 production regressions and 5 more defects (run 5) |
| 5 | 9/28 23:26 | [The review fixes](bob-runs/5-faxcli-fixes.prompt.md) | The fixes plus `tests/test_transport.py`: 189 of 189 tests pass | 50 | 5.165 | Kept. One test was vacuous; the reviewer fixed it and added 2 tests |

**Running total: 14.42 Bobcoins** (after run 5 and the wrapper smoke test).

**Budget.** Pro Plus: 180 Bobcoins for the month, renewing Oct 28, with overage off. We stop and
report at 100 and keep about 30 in reserve for week 3. The per-run cap is 3 unless a step
measurably needs more, and any raise is recorded in this ledger with its reason. `scripts/bob-run.sh`
enforces this.
- It prints the cycle's spend before and after each run.
- It refuses a run that would pass 100 unless `BOB_OVERRIDE="team-lead: <reason>"` is set,
  and it never passes 180. The 180 and the renewal day are constants in
  [`scripts/bob_usage.py`](../scripts/bob_usage.py); only the 100 can be tuned (`BOB_SOFT_CAP`).
  A cost or cap that is not a finite number is refused before Bob starts.
- It keeps this table itself: a row reserved at the run's maximum before Bob starts, and the
  measured cost after it ends. The review columns stay human-written. A cost Bob reports that is
  not a finite number of 0 or more is an error, and the reservation keeps counting.
- It also keeps a journal of every reservation and cost outside the repository, per user and
  per machine, where Bob's sandbox cannot see it. So two checkouts share one budget, a deleted or
  edited row gives no Bobcoins back, and a row that goes missing is restored (the run then exits
  3). A Cost cell must hold a number, or — for none.

**Cap raised for run 4 (the faxcli package): 6.** Run 1 reached 3.08 on reading alone: 26 tool
calls, ~3,300 legacy lines. Run 4 has to read the analysis, the CLI and the fixtures, write about
1,000 lines of code and tests, and iterate on pytest until green. A run stopped by its cap
mid-way would have to re-read everything on resume, which costs more than the headroom.

**Cap for run 5 (review fixes): 5.** Run 4 spent its full 6 and stopped before its own lint and
full-suite pass. A fresh run 5 has to re-read about 1,900 lines of its own package and tests
before it edits them. 3 would likely stop mid-fix again.

## Run notes

### Run 1: modernization analysis
- **What Bob did.** It read all of both programs (18 file reads; the 3,037-line console excerpt
  in ~350-line chunks), wrote a 451-line analysis, then checked its own work unprompted:
  - it found `scripts/scrub-check.sh` in the repo and ran it on its document (the first call
    used the wrong flags and the second passed);
  - it counted the required sections with `grep`.
- **Kept.** The whole document, verbatim. Bob's line citations matched the code in every
  place checked but one. Its findings on duplicated validation, uploads that are never cleaned
  up, the last-line JSON parse and the per-request executor are right, and they shape the
  package design.
- **Rejected or corrected** (details in [analysis §9](analysis.md#9-review-of-this-analysis)):
  - FastAPI for the service: the runtime must stay stdlib-only.
  - `asterisk -T` as a dialplan syntax check: that flag only timestamps output.
  - An overstated "every I/O call raises `SystemExit`".
  - A wrong claim that the CLI prints only JSON under `--json`.
  - "Eight" N11 codes (the list has nine).
  - One misplaced line range.
- **Missed, added in review.** The most important finding: a PBX that cannot be read is
  reported as `ok: true` with every check false. It was demonstrated with the frozen legacy
  code and a failing fake transport. Also missed: an uncaught `TimeoutExpired`, a dead
  cross-check in the VoIP.ms panel, and unbounded per-request threads.
- **Cost note.** Reading about 3,300 lines of legacy code was most of the 3.08. Later runs
  work on the smaller package and should cost less per step.

### Runs 4 and 5: the package
- **What Bob did.** Run 4 wrote the whole package in one pass:
  - pure parsers (`numbers`, `asterisk`, `cdr`, `outcome`, `tiff`);
  - frozen dataclasses that emit the legacy JSON keys in the legacy order;
  - one I/O seam, `transport.py`, with a `Reading(ok, text, why)` result, local, ssh and replay
    transports, and the deliberate change (an unreadable PBX reports `ok: false` with `why` and
    `unread`);
  - 121 tests: unit tests; golden tests against what the real CLI printed from the real PBX; and
    characterization tests that run the frozen legacy code and the new code on the same fixtures.

  Run 4 spent its cap before its own lint pass. Run 5 fixed everything the review found and added
  `tests/test_transport.py`.
- **Kept.** The architecture, `Reading`, the replay transport, the golden and characterization
  tests, and the deliberate change. The commit history shows run 4 exactly as Bob wrote it
  (`feat(faxcli)…by Bob (run 4), before review`), then run 5's fixes.
- **Rejected or fixed, with reasons.**
  - **ssh remote commands were not quoted.** `" ".join(argv)` makes the remote shell split
    `fax show stats`, so Asterisk would run `-rx fax`. The review caught it; replay tests cannot
    see it. Fixed with `shlex.quote`, as legacy did, and pinned by argv tests.
  - **sudo even as the `asterisk` user,** which is how the console runs on the PBX. Every read
    would have failed. Fixed with legacy's rule behind an injectable check.
  - **`FAX_EXCHANGE_HOST` was ignored.** Fixed. Then run 5's test for it turned out to be vacuous:
    it passed the host explicitly. The reviewer fixed it, and a perturbation that pins the default
    turns the test red.
  - **`send` bypassed the seam,** so dry-run tests wrote into `/var/spool`. Moved behind the
    transport.
  - **A test-page default that pointed at the old document path.** Now the neutral
    `demo/test-page.pdf`.
  - **An invented build backend** (`setuptools.backends.legacy:build`, caught by the independent
    review). Now `setuptools.build_meta`.
  - **ruff linted the frozen baseline.** Excluded.
- **Guard moments.**
  - The content scan refused one of Bob's test files over a 15-digit literal. Bob adapted, and the
    rule was later sharpened to real IMSI and IMEI shapes.
  - In run 5, Bob ran `git stash`. The sandbox's read-only `.git` refused it ("Unable to create
    .git/index.lock: Read-only file system"), so the owner's uncommitted work was never at risk.
    The hook guard now refuses every git subcommand that isn't read-only, which gives the same
    answer earlier.
- **The independent review of the PR** (a read-only reviewer agent) found three more, all fixed before merge:
  - **A failed `sudo install` was reported as success.** Bob's code. `spool()` discarded the result, so
    `send` would dial a TIFF that never reached the spool. Legacy aborted there. Fixed by the reviewer,
    with two tests, each proven by a perturbation.
  - **Two false negatives in the scrub gate's new JSON mode**, both the orchestrator's own: a value
    hidden behind a duplicate JSON key, and an address right after a diff's "+". Fixed with regression
    cases.
  - **The conftest subprocess guard could be swallowed** by production code's `except Exception`. It
    now uses `pytest.fail`, a positive control proves it fires, and a blind half-probe is fixed.
- **Kept for week 2** (review items that are real but not blocking):
  - legacy behaviours the port kept on purpose, now candidates for deliberate fixes like finding A:
    a failed originate still reports `ok: true`; a failed "before" stats read counts the delta from
    zero; an empty CDR `file` matches any send;
  - hardening: `mktemp` for temp paths, `--` before the ssh host, the ignored CDR `limit` on the local
    path.
- **Cost.** 6.03 and 5.16. Each run spent its full cap. Fresh runs re-read the package, so
  targeted follow-ups by the reviewer are cheaper for small fixes.

## Who wrote what
| Author | What |
|---|---|
| The owner, before the hackathon | Everything in `legacy/`: the pre-hackathon baseline ([BASELINE.md](../BASELINE.md)). |
| **Bob** | `docs/analysis.md` §1–§8; `faxcli/` and its tests (runs 4 and 5), except the host-reading follow-up. |
| Claude (orchestrating agent) | The baseline scrub and its tooling (`scripts/scrub-check.sh`, hooks, CI), the Bob sandbox (`scripts/bob-sandbox.sh`, `scripts/sandbox-probe.sh`, `.bob/`, `AGENTS.md`, `scripts/bob-*.{sh,py}`, `tests/test_sandbox_guard.py`), review notes (`docs/analysis.md` §9), and this file. The infrastructure hardening came from a second agent, drift-gems: the Bobcoin gate, ledger and journal (`scripts/bob_usage.py`, the budget and tmux handling in `scripts/bob-run.sh`), the `--history` scan, binary review and generic rules in `scripts/scrub-check.sh`, their tests (`tests/test_scrub_*.py`, `tests/test_bob_*.py`) and the CI pins. |
| Oracle (an independent, read-only reviewer agent) | The security review that moved the boundary from hooks to the OS sandbox. |
