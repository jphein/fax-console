# How IBM Bob was used

This file records every Bob run on this project: the prompt, what Bob produced, what was
kept, what was changed or rejected and why, and what it cost. It is the evidence for "Bob as
a core part of the workflow". Each run's raw record is kept under
[`docs/bob-runs/`](bob-runs/). The records are verbatim except for mechanical rewrites made
before publishing:
- the absolute repo path became `.`, and the workstation's home directory became `~`;
- the content of any write the sandbox guard refused is replaced by a placeholder, because that
  content is exactly what the guard keeps out; the tool name, path and reason stay;
- two cellular endpoint names match the rebuilt baseline;
- fictional credential-shaped values that the stricter gate (PRs 2 and 5) cannot tell from real ones were
  renamed to its placeholder form: one test value in run 8 (`fake-…`), and run 7's gate probe
  (`testpassword99` became `test-password-99`, including one fragment split across two stream events).

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
- **Bob follows the repo's own rules.** [`AGENTS.md`](../AGENTS.md) holds them: the frozen
  baseline, no network or PBX access, fictional data only, and stable JSON contracts.
- **The security boundary is an OS sandbox**, [`scripts/bob-sandbox.sh`](../scripts/bob-sandbox.sh).
  Bob's whole process tree runs inside it, including any tests Bob writes and runs:
  - **Filesystem (bubblewrap):** Bob sees this repo and nothing else of the workstation.
    `legacy/`, `.git/`, `.bob/`, `scripts/`, `.github/`, `.venv/` and `AGENTS.md` are
    read-only. Bob gets a clean home directory and a minimal `/etc`, with no hosts file and no
    ssh config.
  - **Network (a systemd scope with BPF address filters):** the LAN, loopback, link-local and
    CGNAT ranges are denied, so the PBX and every house service are unreachable. The public
    internet stays open for Bob's own API.
  - **Processes:** Bob gets its own PID, IPC and UTS namespaces, and a new session.
  - [`scripts/sandbox-probe.sh`](../scripts/sandbox-probe.sh) proves the containment with
    35 probes. One is a live positive control: ssh to the real PBX succeeds outside the
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
  - [`tests/test_sandbox_guard.py`](../tests/test_sandbox_guard.py) has 65 cases.
- **Tests run only inside the sandbox** ([`scripts/test.sh`](../scripts/test.sh)), and
  [`tests/conftest.py`](../tests/conftest.py) fails any test that spawns a process or binds or
  connects an IP socket. The sandbox's packet filter cannot see a bind, and it lets the public
  internet through for Bob's own API, so the "no TCP, no network" rule for tests is enforced there.
- **The orchestrating agent (Claude) reviews everything Bob writes.** It checks claims against
  the code and records corrections here. Nothing Bob writes is committed unread.
- **Commits whose content Bob wrote carry an `Assisted-by: IBM Bob` trailer**, so
  `git log --grep "Assisted-by: IBM Bob"` lists them.

## Timeline by day
Judges asked to see Bob "in every process from day one". Each Bob task id below can be found in its
recording under `docs/bob-runs/`, and each run is its own commit.

**Mon 2026-09-28** (day 1; the window opened at 16:00 PDT)

| Time (PDT) | Run | Bob task | What Bob did | Outcome | Bobcoins |
|---|---|---|---|---|---|
| 21:30 | setup | `69b2171c` | answered a one-word account check | — | 0.027 |
| 22:13 | 0 | `f40a8f15` | the sandbox smoke test: one write allowed, `curl` and an outside read refused | proved the hooks fire headless | 0.083 |
| 22:15 | 1 | `57dd9a07` | the modernization analysis (`docs/analysis.md` §1–§8) | kept verbatim; 7 corrections and 6 added findings in review | 3.078 |
| 22:34 | 2 | — | nothing: the prompt gate refused the prompt (failed closed) | led to the OS sandbox's split rules | 0 |
| 22:41 | 3 | `dffca676` | "ok", from inside the OS sandbox | proved the clean home: only Bob's own skills listed | 0.021 |
| 23:02 | 4 | `7f24d791` | the `faxcli` package and 121 tests | architecture kept; 2 production regressions found in review | 6.027 |
| 23:19 | 5 | `eded36dd` | the review fixes and transport tests | kept; `git stash` refused by the sandbox (23:24:32) | 5.165 |
| 23:57 | 6 | `262e87a5` | the `faxconsole` core (week 2 begins) and 103 tests | kept; review items go to run 7 | 8.022 |

**Tue 2026-09-29** (day 2)

| Time (PDT) | Run | Bob task | What Bob did | Outcome | Bobcoins |
|---|---|---|---|---|---|
| 00:13 | 7 | `0b7f46c4` | run 6's review items (replay isolation, typed send API, bounded queue) and the VoIP.ms poller | Part 1 kept; the poller's tests were refused by the guard, so run 8 finishes it | 10.225 |
| 00:40 | 8 | `eeebacd0` | finished the VoIP.ms port: 4 fixes, replay wiring with cleanup, 50 tests and the legacy characterization | kept; the first run under its cap with its summary; review strengthened 7 tests | 4.975 |
| 01:05 | 9 | `5a76155a` | the page: Live state, PSTN account and Fax, served by `handle()` with a CSP; dark and light; 41 tests | kept; review found the public demo would publish its host's name (fixed), a dark theme that never reached the favicon or form controls, and tests blind to CSP breakage | 4.615 |

## Ledger
Costs are Bob Shell's `session_costs`, the Bobcoin figure. The budget is below the table.

| # | Date (PDT) | Task | Bob's output | Tool calls | Cost | Kept / changed |
|---|---|---|---|---|---|---|
| – | 9/28 21:30 | Setup check ("reply ok") | one word | 0 | 0.027 | — |
| 0 | 9/28 22:13 | [Sandbox smoke test](bob-runs/0-sandbox-smoke.prompt.md) | one file written; `curl` refused; an outside path refused | 3 | 0.083 | Proved the hooks fire in headless mode and that Bob reports refusals accurately |
| 1 | 9/28 22:15 | [Modernization analysis](bob-runs/1-analysis.prompt.md) | [`docs/analysis.md`](analysis.md) §1–§8, 451 lines | 26 | 3.078 | Kept verbatim; 7 corrections and 6 added findings in §9 |
| 2 | 9/28 22:34 | [Isolation check](bob-runs/2-isolation-check.prompt.md) | none: the prompt gate refused the prompt, failing closed, because the private deny-list was not reachable from the clean home | 0 | 0 | Showed the gate fails closed; led to the sandbox's split between generic rules inside and the private list outside |
| 3 | 9/28 22:41 | [Sandbox check](bob-runs/3-sandbox-check.prompt.md) | "ok", from inside the OS sandbox | 0 | 0.021 | Proved Bob works sandboxed; its prompt now lists only Bob's own six skills |
| 4 | 9/28 23:02 | [The faxcli package](bob-runs/4-faxcli-package.prompt.md) | `faxcli/` (9 modules, ~905 lines), `pyproject.toml`, 121 tests (unit, golden, characterization) | 58 | 6.027 | Architecture kept. Review found 2 production regressions and 5 more defects (run 5) |
| 5 | 9/28 23:19 | [The review fixes](bob-runs/5-faxcli-fixes.prompt.md) | The fixes plus `tests/test_transport.py`: 189 of 189 tests pass | 50 | 5.165 | Kept. One test was vacuous; the reviewer fixed it and added 2 tests |
| 6 | 9/28 23:57 | [The faxconsole core](bob-runs/6-faxconsole-core.prompt.md) | `faxconsole/` (888 lines): pure `handle()`, PBX readers, the write gate, a pooled server, sigil; 103 tests | 62 | 8.022 | Kept. Review: replay mode lacks a temp spool/inbox; send still parses CLI output; `--ssh` pins the host (run 7) |
| 7 | 9/29 00:13 | [Run 6's review and the VoIP.ms poller](bob-runs/7-voipms-and-replay.prompt.md) | replay temp dir, `Config(replay=True)` check, `--ssh` host, `faxcli/api.py` (typed send), a bounded queue with 503; `faxconsole/voipms.py` (391 lines), 3 synthesized fixtures, `GET /api/voipms`; 16 tests | 69 | 10.225 | Part 1 kept. Review: the 503 test bound TCP and was vacuous, and the 503 was lost to a reset (fixed by the reviewer). The poller's tests were refused by the guard; run 8 finishes them |
| 8 | 9/29 00:40 | [Finish the VoIP.ms port](bob-runs/8-voipms-finish.prompt.md) | the 4 review fixes in `voipms.py`; `fixture_http`; `build(argv)` with cleanup and SIGTERM; 50 tests, 17 of them characterization against the legacy poller; a work log ([worklog](bob-runs/8-voipms-finish.worklog.md)) | 46 | 4.975 | Kept. Review: 5 perturbations left Bob's tests green (two mechanisms masked each other, a vacuous `__cause__` check, 12 chosen fields); fixed with whole-snapshot equality. The credentials error text had changed from legacy's (fixed) |
| 9 | 9/29 01:05 | [The page](bob-runs/9-page.prompt.md) | `faxconsole/static/` (index.html, app.css, app.js, favicon.svg), served by `handle()` with a CSP and nosniff; replay banner from `/api/version`; 41 tests; a work log ([worklog](bob-runs/9-page.worklog.md)) | 44 | 4.615 | Kept. Review (a visual check, light and dark, on a static export): the sigil's `host` would publish the demo host's name (fixed); the favicon's dark rules never applied; native controls stayed light; the tests missed inline handlers, a weakened `script-src` and a 503 |

**Running total: 42.24 Bobcoins** (after run 9). Drift's 0.016 wrapper smoke test is recorded on its own branch.

**Budget.** Pro Plus: 180 Bobcoins for the month, renewing Oct 28, with overage off. We stop and
report at 100 and keep about 30 in reserve for week 3. The per-run cap is 3 unless a step
measurably needs more, and any raise is recorded in this ledger with its reason.

**Cap raised for run 4 (the faxcli package): 6.** Run 1 reached 3.08 on reading alone: 26 tool
calls, ~3,300 legacy lines. Run 4 has to read the analysis, the CLI and the fixtures, write about
1,000 lines of code and tests, and iterate on pytest until green. A run stopped by its cap
mid-way would have to re-read everything on resume, which costs more than the headroom.

**Cap for run 5 (review fixes): 5.** Run 4 spent its full 6 and stopped before its own lint and
full-suite pass. A fresh run 5 has to re-read about 1,900 lines of its own package and tests
before it edits them. 3 would likely stop mid-fix again.

**Cap for run 10 (the inbound dialplan as generated config): 5.** The plan said 4. Runs 8 and 9 spent
4.97 and 4.61 on similar-sized scopes (a module, about 300 lines of tests, a work log), so 4 would likely
stop short of the tests. The work log keeps any partial progress visible.

**Cap for run 9 (the page): 8,** as planned. It ports the page's PBX pieces (about 450 lines of
legacy markup, CSS and JS, read in ranges), writes four static files and 20 or more tests, and keeps the
work log that brought run 8 in under its cap.

**Cap for run 8 (finish the VoIP.ms port): 7.** Run 7 spent 0.15 per tool call. Run 8 re-reads
about 900 lines (the poller, the legacy poller and the legacy-import pattern), then writes about 400
lines of tests and a small refactor of `__main__`, and iterates: an estimated 45 tool calls. The
prompt asks for a work log after each item, because runs 4–7 all ended at their cap before their
final summary; Bob Shell does not show the model its own spend.

**Cap for run 7 (the VoIP.ms poller plus run 6's review items): 10.** Runs 4–6 each spent their full
cap (6, 5, 8). Run 7 combines two planned pieces of work to avoid a second full re-read, so it is
capped at the sum of their plan caps (6 + 4). That is under the 15 that needs the lead's word.

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

### Runs 6 and 7: the service
- **What Bob did.** Run 6 extracted the Fax panel's back end and the PBX status readers into
  `faxconsole/`:
  - a pure `handle(method, path, headers, body)`, and an `http.server` adapter on a fixed pool of
    8 workers (analysis finding F);
  - the PBX readers over faxcli `Reading`s, keeping the legacy meaning of "not probed";
  - the write gate (token, confirm, size, PDF), the realm-sigil version contract, and replay mode;
  - 103 tests, driven through `handle()` and over AF_UNIX socketpairs, with characterization
    against the frozen legacy readers.

  Run 7 worked through run 6's review, then started the VoIP.ms poller:
  - replay mode uses one temp dir, and `Config(replay=True)` refuses a live transport;
  - `faxcli/api.py`, a typed `send()`, so the console no longer parses the CLI's printed JSON;
  - a bounded queue: 8 workers plus 4 waiting, and then a 503 with `Retry-After`;
  - `faxconsole/voipms.py`, the poller with injectable I/O, and three synthesized fixtures.
- **Kept.**
  - Run 6's design.
  - Run 7's Part 1.
  - The poller's port, which keeps every legacy rule in its comments.
- **Rejected or fixed, with reasons.**
  - **Run 6: four review items, all fixed in run 7.**
    - Replay dry runs rendered into the real spool path, and uploads went to a permanent inbox.
    - `--ssh` pinned the host.
    - The console still built an `argparse.Namespace` and parsed printed JSON.
    - The queue was unbounded.
  - **Run 7's over-capacity test bound a TCP socket,** which the rules forbid. It passed only
    because the sandbox filters packets, not binds. It was also vacuous: it wrote the 503 by hand
    and never went through the capacity check.
    - The reviewer replaced it with tests that hand `process_request` one end of a socketpair.
    - conftest now fails any test that binds or connects an IP socket. Bob's test was the only one
      of 321 to go red under the new guard.
  - **Those tests found a real bug.** The 503 was written, then the socket closed with the request
    unread. The kernel reset the connection, so the client saw a reset, not the 503.
    - Fixed with a bounded, non-blocking drain.
    - Three perturbations each turn the tests red: no capacity check, no release, no drain.
  - **Review items for run 8.**
    - `days_to_billing` ignores the injected clock.
    - The legacy 403 hint was dropped. (That hint says a bare 403 is usually the WAF rejecting the
      User-Agent.)
    - `stop()` can take 30 s.
    - Replay mode does not start the poller.
    - The poller has no tests.
- **Guard moments.**
  - **Run 6.** Three writes were refused:
    - one write outside the repo, a path slip;
    - two test numbers outside the fictional 555-01xx block, which Bob rewrote.
  - **Run 7.** Bob's poller test file was refused: a credential-shaped assignment appeared in it
    literally, although its values were fictional. Bob was probing the gate to restructure the file
    when the cap stopped the run. The refused content is not published.
- **Cost.** 8.02 and 10.23, each the full cap. Neither run reached its final summary, so run 8's
  prompt asks for a work log after each item.

### Run 8: finishing the VoIP.ms port
- **What Bob did.** Bob fixed the four review items in `voipms.py`:
  - the clock is injected everywhere;
  - legacy's 403 hint is back;
  - `stop()` takes effect within one tick;
  - ruff is clean.

  Then it added a fixture HTTP for replay mode, an injectable credentials source, and `build(argv)`, which
  returns a config and a cleanup that also runs on SIGTERM. It wrote 50 tests, including 17 that
  characterize the frozen legacy poller at a fresh and a stale clock.
  - It kept the work log the prompt asked for, finished under its cap (4.97 of 7), and gave its summary:
    the first run to do both.
- **Kept.** All of it.
- **Rejected or fixed, with reasons.**
  - **Five perturbations of the production code left all 50 tests green.** The reviewer's fixes turn
    each one red:
    - **The two scrub mechanisms were never tested apart.** Every test string carried `api_password=`,
      which legacy rewrites always. The values had no characters that URL encoding changes, so the
      "encoded" form was the plain value, and each mechanism covered for the other.
    - **`__cause__ is None` proves nothing:** implicit chaining leaves it None too. The test now formats
      the traceback, as a log would, and looks for the password.
    - **The characterization compared 12 chosen fields.** Whole-snapshot equality now covers the rest.
    - **The replay test accepted any dict.** It now reads the synthesized balance.
  - **The credentials error text had changed** when the source became injectable. It is part of the
    snapshot's JSON contract, and legacy names the path. The legacy text is back, proved against the
    legacy poller.
  - **Two legacy rule comments were dropped** in the lint refactor. They are restored.
  - **One fictional test value** did not use the `fake-…` form the prompt asked for. It was renamed
    before the commit, because the gate landing with PR 2 cannot tell it from a real one.
- **Kept for the review-fixes run.**
  - `main()` builds the server outside its `try`, so a failed bind skips cleanup.
  - `main()` re-parses argv with a second parser.
- **Cost.** 4.97.

### Run 9: the page
- **What Bob did.** Bob ported the page's Live state, PSTN account and Fax sections from the legacy
  template into four static files, keeping every legacy element id and the rule comments. They are
  served by `handle()` with a CSP that allows no inline script, plus `nosniff`.
  - The JS reads only this service's routes. A replay banner comes from `/api/version`, and the write
    token is held in memory only.
  - It wrote 41 tests and finished under its cap (4.61 of 8), with its work log and summary.
- **Kept.** The port and the routes.
- **Rejected or fixed, with reasons.** The review looked at the page in a browser, light and dark, on a
  static export that `handle()` wrote inside the sandbox. It used the same CSP as a meta tag, and the
  console showed no violations.
  - **The public demo would publish its host's name.** The sigil's `host` is the machine's name. In
    replay mode, which is the public demo, it now reads "replay".
  - **The favicon's dark rules never applied.** They came before the defaults at equal specificity.
  - **The dark theme left native form controls light.** `color-scheme` is now declared.
  - **The footer read "vAmplified Antenna".**
  - **The tests could not see a broken page.** Inline handlers fail silently under the CSP, a substring
    check passes a weakened `script-src`, and "non-404" passes a 503. Five perturbations each turn the
    new tests red. One of the reviewer's own new tests first came back green: it counted the media
    query's `prefers-color-scheme:dark` as a declaration.
- **For the lead.** The Active-calls tile and the backend keep legacy's instrument name "MSC
  connections". It is part of the characterized JSON contract.
- **Cost.** 4.61.

## Who wrote what
| Author | What |
|---|---|
| The owner, before the hackathon | Everything in `legacy/`: the pre-hackathon baseline ([BASELINE.md](../BASELINE.md)). |
| **Bob** | `docs/analysis.md` §1–§8; `faxcli/` and its tests (runs 4 and 5), except the host-reading follow-up; `faxcli/api.py` and `faxconsole/` with their tests and its page (runs 6–9), except the reviewer fixes named in the run notes. |
| Claude (orchestrating agent) | The baseline scrub and its tooling (`scripts/scrub-check.sh`, hooks, CI), the Bob sandbox (`scripts/bob-sandbox.sh`, `scripts/sandbox-probe.sh`, `.bob/`, `AGENTS.md`, `scripts/bob-*.{sh,py}`, `tests/test_sandbox_guard.py`, the network guard and the process guard's hardening in `tests/conftest.py`), review notes (`docs/analysis.md` §9), and this file. |
| Oracle (an independent, read-only reviewer agent) | The security review that moved the boundary from hooks to the OS sandbox. |
