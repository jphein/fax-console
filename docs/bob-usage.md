# How IBM Bob was used

This file records every Bob run on this project: the prompt, what Bob produced, what was
kept, what was changed or rejected and why, and what it cost. It is the evidence for "Bob as
a core part of the workflow". Each run's raw record is kept under
[`docs/bob-runs/`](bob-runs/):

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
- **Bob is sandboxed by its own hook system** ([`.bob/settings.json`](../.bob/settings.json)):
  - [`prompt_gate.py`](../.bob/hooks/prompt_gate.py) runs every prompt through the scrub gate
    before Bob sees it (rules §8.6: no personal data to AI tools).
  - [`tool_guard.py`](../.bob/hooks/tool_guard.py) refuses network, remote, privileged and PBX
    commands; paths outside the repo; writes to the frozen baseline or to the guard itself; and
    any write whose content carries identifying data.
  - Both hooks fail closed.
  - [`tests/test_sandbox_guard.py`](../tests/test_sandbox_guard.py) has 50 cases, and every rule
    has one case that must pass and one that must be refused.
- **The orchestrating agent (Claude) reviews everything Bob writes.** It checks claims against
  the code and records corrections here. Nothing Bob writes is committed unread.

## Ledger
Costs are Bob Shell's `session_costs`, the Bobcoin figure. The trial budget is 50 for the month.

| # | Date (PDT) | Task | Bob's output | Tool calls | Cost | Kept / changed |
|---|---|---|---|---|---|---|
| – | 9/28 21:30 | Setup check ("reply ok") | one word | 0 | 0.027 | — |
| 0 | 9/28 22:13 | [Sandbox smoke test](bob-runs/0-sandbox-smoke.prompt.md) | one file written; `curl` refused; an outside path refused | 3 | 0.083 | Proved the hooks fire in headless mode and that Bob reports refusals accurately |
| 1 | 9/28 22:15 | [Modernization analysis](bob-runs/1-analysis.prompt.md) | [`docs/analysis.md`](analysis.md) §1–§8, 451 lines | 26 | 3.078 | Kept verbatim; 7 corrections and 6 added findings in §9 |

**Running total: 3.19 Bobcoins** (after run 1).

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
| Claude (orchestrating agent) | The baseline scrub and its tooling (`scripts/scrub-check.sh`, hooks, CI), the Bob sandbox (`.bob/`, `AGENTS.md`, `scripts/bob-*.{sh,py}`, `tests/test_sandbox_guard.py`), review notes (`docs/analysis.md` §9), and this file. |
