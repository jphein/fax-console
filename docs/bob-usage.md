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
    31 probes. One is a live positive control: ssh to the real PBX succeeds outside the
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
Costs are Bob Shell's `session_costs`, the Bobcoin figure. The trial budget is 50 for the month.

| # | Date (PDT) | Task | Bob's output | Tool calls | Cost | Kept / changed |
|---|---|---|---|---|---|---|
| – | 9/28 21:30 | Setup check ("reply ok") | one word | 0 | 0.027 | — |
| 0 | 9/28 22:13 | [Sandbox smoke test](bob-runs/0-sandbox-smoke.prompt.md) | one file written; `curl` refused; an outside path refused | 3 | 0.083 | Proved the hooks fire in headless mode and that Bob reports refusals accurately |
| 1 | 9/28 22:15 | [Modernization analysis](bob-runs/1-analysis.prompt.md) | [`docs/analysis.md`](analysis.md) §1–§8, 451 lines | 26 | 3.078 | Kept verbatim; 7 corrections and 6 added findings in §9 |
| 2 | 9/28 22:34 | [Isolation check](bob-runs/2-isolation-check.prompt.md) | none: the prompt gate refused the prompt, failing closed, because the private deny-list was not reachable from the clean home | 0 | 0 | Showed the gate fails closed; led to the sandbox's split between generic rules inside and the private list outside |
| 3 | 9/28 22:44 | [Sandbox check](bob-runs/3-sandbox-check.prompt.md) | "ok", from inside the OS sandbox | 0 | 0.021 | Proved Bob works sandboxed; its prompt now lists only Bob's own six skills |

**Running total: 3.21 Bobcoins** (after run 3).

**Budget.** Pro Plus: 180 Bobcoins for the month, renewing Oct 28, with overage off. We stop and
report at 100 and keep about 30 in reserve for week 3. The per-run cap is 3 unless a step
measurably needs more, and any raise is recorded in this ledger with its reason.

**Cap raised for run 4 (the faxcli package): 6.** Run 1 reached 3.08 on reading alone: 26 tool
calls, ~3,300 legacy lines. Run 4 has to read the analysis, the CLI and the fixtures, write about
1,000 lines of code and tests, and iterate on pytest until green. A run stopped by its cap
mid-way would have to re-read everything on resume, which costs more than the headroom.

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

## Who wrote what
| Author | What |
|---|---|
| The owner, before the hackathon | Everything in `legacy/`: the pre-hackathon baseline ([BASELINE.md](../BASELINE.md)). |
| **Bob** | `docs/analysis.md` §1–§8. |
| Claude (orchestrating agent) | The baseline scrub and its tooling (`scripts/scrub-check.sh`, hooks, CI), the Bob sandbox (`scripts/bob-sandbox.sh`, `scripts/sandbox-probe.sh`, `.bob/`, `AGENTS.md`, `scripts/bob-*.{sh,py}`, `tests/test_sandbox_guard.py`), review notes (`docs/analysis.md` §9), and this file. |
| Oracle (an independent, read-only reviewer agent) | The security review that moved the boundary from hooks to the OS sandbox. |
