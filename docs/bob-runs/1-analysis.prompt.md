You are modernizing the legacy code in `legacy/`: a fax CLI (`legacy/fax/`) and an excerpt of a single-file web console (`legacy/console/telephony-console.py`). Read `AGENTS.md` and `BASELINE.md` first. Then read all of `legacy/fax/fax/cli.py`, `legacy/fax/CLAUDE.md`, `legacy/fax/docs/*.md`, and all of the console excerpt. It is about 3,000 lines, so read it in chunks. Do not skip parts.

Write ONE file, `docs/analysis.md`: a modernization analysis that a reviewer can verify line by line. Do not create or change any other file. Every factual claim must cite `path:line` (or a line range) in `legacy/`. If you are unsure of something, say so rather than guess. Use only the fictional example numbers the repo already uses.

Sections, in this order:

1. **Summary.** What the two programs do, how they connect, and the five findings that matter most for modernization.
2. **Module map of the console excerpt.** Each kept region: what it does, its line range, and what it depends on. Include the request flow for the Fax panel end to end: browser → `/api/fax` and `/api/fax/send` → handler → `fax_state`/`fax_send` → `fax_cli` → the CLI → Asterisk. Also cover the PBX status flow: `/api/state` → `snapshot()` → readers → `ast()`, and the VoIP.ms poller thread.
3. **CLI map.** Every function in `cli.py`, each classified as **pure** (a deterministic transform of its inputs) or **I/O** (process, ssh, file, clock or sleep). For I/O functions, name the seam that would make them testable.
4. **Shell-out inventory.** A table of every `subprocess` call and every Asterisk CLI command, in both programs. Columns: location, argv/command, local or over ssh, sudo, timeout, error handling, what a failure looks like to the caller. State explicitly whether `shell=True` appears anywhere.
5. **Unsafe or fragile patterns.** Look at least for:
   - library code that exits the process;
   - broad `except` clauses that hide failures;
   - validation duplicated between the console and the CLI (drift risk);
   - unbounded threads, executors or caches;
   - credentials in URLs or in error paths;
   - request-body handling;
   - files that are written and never cleaned up;
   - time zones;
   - dead or never-true code paths;
   - brittle text parsing of Asterisk output.

   For each finding give its location, why it matters, the severity (high/medium/low), and a concrete fix. Keep what is fine: say so when a pattern that looks risky is actually handled.
6. **The JSON contracts.** The exact shapes the console consumes (`status`, `log`, `send`, `send --dry-run`), field by field with types, derived from the code, not just the docs. Note any field the docs promise that the code does not produce, or the reverse. These become typed dataclasses and must stay stable.
7. **Test plan.** The pure functions to test first. The recorded command outputs needed as fixtures (one per Asterisk command, plus CDR rows), with realistic but fictional content. The edge cases each test must cover.
8. **Migration order.** Small, reversible steps, each with its risk and how to verify it:
   - (a) the CLI becomes a package with pure functions, dataclasses and tests;
   - (b) one Asterisk adapter seam that can replay fixtures;
   - (c) the Fax panel extracted into a small service with a typed API and a replay mode;
   - (d) the inbound-fax design from `docs/inbound.md` as generated config and tests only, never deployed.

Keep it under about 450 lines. Plain, direct English.
