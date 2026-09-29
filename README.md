# fax-console

Modernizing a working house-PBX fax service (a Python CLI around Asterisk `SendFax`, plus
the fax and PBX-status slice of an 11,858-line single-file web console) with **IBM Bob**,
for the *Building with IBM Bob* hackathon, track **Modernize What Matters**.

> **Status: week 1, in progress.** Only the pre-hackathon baseline and the safety tooling are
> in the repo so far. This README grows as the work lands.

## What is here

| Path | What |
|---|---|
| [`legacy/`](legacy/) | The **pre-hackathon baseline**, frozen: the fax CLI and the console excerpt, scrubbed and otherwise unchanged. See [BASELINE.md](BASELINE.md) for sources, dates and exactly what scrubbing changed. |
| [`scripts/scrub-check.sh`](scripts/scrub-check.sh) | The gate that keeps personal and house-network data out of commits, commit messages, CI and AI prompts. |
| `faxcli/` *(week 1)* | The CLI as a typed, tested package: pure parsing split from I/O. |
| `faxconsole/` *(week 2)* | The Fax panel extracted into a small service with a typed API and a replay mode. |
| `docs/` | The modernization analysis and the record of how Bob was used. |

## Ground rules

- **No real fax is ever sent from this repo's demo.** Sends go to the Faxbeep public tester,
  or run with `--dry-run`. The live demo runs on recorded fixtures, never against a PBX.
- **Nothing identifying is published.** Run `scripts/install-hooks.sh` once per clone. After
  that, every commit and commit message passes through `scripts/scrub-check.sh`, and CI runs
  it again.
- **`legacy/` never changes.** CI fails if it drifts from the `baseline-2026-09-28` tag.

## License

AGPL-3.0-or-later © 2026 Jeffrey Pine Hein. See [LICENSE](LICENSE).
