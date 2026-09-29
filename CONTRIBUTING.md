# Contributing

- **Tests.** `scripts/test.sh` runs pytest and ruff inside the OS sandbox. On the maintainer's workstation, the suite runs only that way (see the script's header).
- **The scrub gate** runs on every commit and every push (`scripts/install-hooks.sh`). It checks against a private list of real values that never leaves the maintainer's machine. Test vectors are fictional: 202-555-01xx numbers, `*.example.com` hosts, documentation IP ranges.
- **Commit messages cite agents and reviewers by name or a short prefix, never a full agent id.** A full id is a run of hex digits, and those digits can look like a phone number. #17's squash message tripped the phone rule that way. The gate now exempts exactly this team's agent-id shape (`a` and 16 hex). Even so, the habit is a name ("the Oracle") or a 7-character prefix.
- AI agents also follow [`AGENTS.md`](AGENTS.md).
