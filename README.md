# fax-console

A house PBX's legacy fax tools, modernized with **IBM Bob** while the phone line kept working.

**Building with IBM Bob hackathon · track Modernize What Matters** · Live demo (replay mode):
{{demo.url}} · Video: {{video.url}} · Deck: [`docs/deck.pdf`](docs/deck.pdf)

> **Status: week 2 of 3.** The pre-hackathon baseline, the safety tooling, Bob's modernization
> analysis, the `faxcli` package and the `faxconsole` service with its replay mode are here. This
> README grows as the work lands.

## What it is

Two pieces of legacy house code, modernized during the hackathon:

- **`fax`** is a 288-line send-only fax CLI around Asterisk `SendFax`. It converts a PDF with
  ghostscript, shells out to the PBX (over ssh when run remotely), has no tests, and prints the
  JSON the console reads. It becomes **`faxcli/`**: pure parsing split from I/O, typed dataclasses
  for that JSON, and tests on recorded fixtures.
- **The Fax panel of an 11,858-line single-file web console.** That console serves every panel
  from one stdlib `ThreadingHTTPServer`, with hand-rolled routing, and shells out for every
  read. Its Fax panel and the Asterisk and VoIP.ms status code become **`faxconsole/`**, a small
  typed API behind one Asterisk adapter, with a **replay mode** that runs on recorded fixtures.

The untouched originals are in [`legacy/`](legacy/). The console excerpt keeps 3,009 of its
lines verbatim, and [BASELINE.md](BASELINE.md) says exactly what was left out and why.

## Why it matters

This is the kind of code the track is about. It has no framework and no tests, it runs in
production, and it has to keep working. The old console reaches the phone system from 11
shell-out call sites ([analysis §4](docs/analysis.md#4-shell-out-inventory)). The modernized
one has a single way in: the Asterisk adapter. Point that adapter at fixtures and the whole
console can be tested and demonstrated without touching a phone line.

## What is here

| Path | What |
|---|---|
| [`legacy/`](legacy/) | The **pre-hackathon baseline**, frozen: the fax CLI and the console excerpt, scrubbed and otherwise unchanged. See [BASELINE.md](BASELINE.md) for sources, dates and exactly what scrubbing changed. |
| [`scripts/scrub-check.sh`](scripts/scrub-check.sh) | The gate that keeps personal and house-network data out of commits, commit messages, CI and AI prompts. |
| [`faxcli/`](faxcli/) | The CLI as a typed, tested package: pure parsing split from I/O, a typed send API (`faxcli/api.py`), and the inbound-fax design as generated config (`faxcli/inbound.py`). |
| [`faxconsole/`](faxconsole/) | The Fax panel extracted into a small service: a typed API, the page, and a replay mode on recorded fixtures. |
| [`docs/`](docs/) | The modernization analysis, the record of how Bob was used, every deliberate change from the legacy behaviour ([`docs/changes.md`](docs/changes.md)), the [deck](docs/deck/) and the [demo video plan](docs/video/). |
| [`demo/`](demo/) | The page the demo's `fax test --pdf` sends: [`demo/test-page.pdf`](demo/test-page.pdf), no personal information. |

## Run it in replay mode

Replay mode needs no PBX and only the Python standard library. The adapter reads the fixtures in
`tests/fixtures/`: the PBX and CDR data were recorded on 2026-09-28 and scrubbed, and the VoIP.ms
data are sample data (illustrative, not a real account). Status, the fax log and the send form all
work, and nothing can dial.

```bash
git clone https://github.com/jphein/fax-console && cd fax-console
python3 -m faxconsole --replay tests/fixtures    # the console on fixtures at http://127.0.0.1:8093
```

In replay mode, every `POST /api/fax/send` is forced to a dry run. The GET routes are `/` (the
page), `/api/fax` (the panel's state), `/api/fax/status`, `/api/fax/log`, `/api/voipms` (the
balance: sample data in replay), `/api/pbx/trunk`, `/api/pbx/calls`, `/api/pbx/endpoints` and
`/api/version`. The one POST route is `/api/fax/send`.

A static copy of the replay runs on GitHub Pages at https://jphein.github.io/fax-console/. It has
the same views, from the same fixtures, with sending off. [`docs/deploy.md`](docs/deploy.md) says
how that copy is built, checked and published, and how to self-host the replay server.

### Run the tests

The runtime is the Python 3.10+ standard library. The tests need pytest, and lint uses ruff.

```bash
python3 -m pip install pytest ruff
python3 -m pytest -q    # fixtures and mocked I/O only: no network, no PBX
ruff check .
```

On every push, CI runs ruff and the tests on Python 3.10, 3.12 and 3.14, the scrub gate's generic
rules, and a check that `legacy/` has not changed since the baseline. A private list of the real
values gates every commit locally and never leaves the owner's machine.

### The one live send

`fax test` sends a test page to [Faxbeep](https://faxbeep.com), a public test inbox, and never to
a person. Everything else in the demo uses `--dry-run`.

## How IBM Bob was used

Bob writes the modernization one step at a time: first the analysis
([`docs/analysis.md`](docs/analysis.md)), then the `faxcli` package and its tests, then the
`faxconsole` service with its adapter, replay mode and page.

- **Bob Shell, headless.** Every run is recorded under [`docs/bob-runs/`](docs/bob-runs/): the
  exact prompt, Bob's stream-json transcript, and every allow or deny decision its hooks made.
- **Inside an OS sandbox.** Bob Shell runs in a bubblewrap filesystem view behind a systemd BPF
  network filter (`scripts/bob-sandbox.sh`), with a fresh home directory for every run and Bob's
  gateway pinned by a read-only policy. 50 containment probes prove it as of 623b50d, including a
  live control; `scripts/sandbox-probe.sh` counts them at run time.
- **Audited by Bob's own hooks.** On top of the sandbox, a prompt gate runs every prompt through
  the scrub gate before Bob sees it, and a tool guard refuses network, PBX and privileged
  commands, paths outside the repo, writes to the frozen baseline, and any write that carries
  identifying data. Both fail closed.
- **Proven by a real event.** In run 5, Bob ran `git stash` while comparing lint results. The
  sandbox's read-only `.git` refused it (`Unable to create './.git/index.lock': Read-only file
  system`), so the owner's uncommitted work was never at risk. The hook guard, a regex, had not
  listed `stash`; it now allows only read-only git. The recording is
  [`docs/bob-runs/5-faxcli-fixes.jsonl`](docs/bob-runs/5-faxcli-fixes.jsonl).
- **A real find.** In run 10, Bob found, unaided, that the legacy inbound-fax design passed the
  caller's number (`${CALLERID(num)}`) to `System()`, which runs a shell, and into a file path. It
  wrapped both in `FILTER()`. Review narrowed the filter to digits and `+`, because a hyphen let a
  caller pass `--flag` to the notify program. The design was never deployed
  ([run 10 notes](docs/bob-usage.md#run-10-the-inbound-dialplan)).
- **Everything reviewed.** [`docs/bob-usage.md`](docs/bob-usage.md) is the ledger: each run's
  task, cost, and what was kept, changed or rejected, and why. Bob's commits carry an
  `Assisted-by: IBM Bob` trailer. At submission: Bob factor {{bob.factor_pct}} (Bob's share of the
  new code and test lines), and {{bob.commits}} Bob-assisted commits, one per run that changed files.

## Ground rules

- **No real fax is ever sent from this repo's demo.** Sends go to the Faxbeep public tester,
  or run with `--dry-run`. The replay demo runs on recorded fixtures, never against a PBX.
- **Nothing identifying is published.** Run `scripts/install-hooks.sh` once per clone. After
  that, every commit and commit message passes through `scripts/scrub-check.sh`, and CI runs
  it again.
- **`legacy/` never changes.** CI fails if it drifts from the `baseline-2026-09-28` tag.
- **Bob works inside an OS sandbox** ([`scripts/bob-sandbox.sh`](scripts/bob-sandbox.sh)). It
  sees only this repository, has no route to the LAN, and gets a fresh home directory for every
  run. [`scripts/sandbox-probe.sh`](scripts/sandbox-probe.sh) checks the containment: 50 probes as
  of 623b50d, counted at run time.

## Hackathon notes

- **Track:** Modernize What Matters (Experienced Developers).
- **Existing project and the Fresh Code Rule (rules §6.5, §7):** commit #1 (tag
  `baseline-2026-09-28`) is the pre-hackathon baseline, scrubbed and otherwise unchanged. It
  was rebuilt once, on day one, to scrub two endpoint names ([BASELINE.md](BASELINE.md)).
  Every later commit was written during the hackathon window. The Improvements Made statement (§6.3.3) is in the
  [deck](docs/deck.pdf), slide 6, and every deliberate change from the legacy behaviour, with its
  tests, is in [`docs/changes.md`](docs/changes.md).
- **No private data in AI tools (rules §8.6):** the baseline was scrubbed before any AI tool saw
  it, and every Bob prompt passes the scrub gate first. Fixtures use the fictional
  `555-0100` to `555-0199` numbers and `example.com` hosts. The console's cellular half is not in
  this repository.

## Credits and licenses

- **Jeffrey Hein** wrote the legacy code. He reviews and approves the modernization at two
  checkpoints.
- **IBM Bob** writes the modernization: the analysis, and most of the packages, the page and their
  tests.
  IBM Bob is IBM Technology, used under the hackathon terms.
- **Claude (Anthropic)** built the scrub gate and the Bob sandbox, drives Bob Shell, reviews each
  change against the code, and drafted this README, the deck and the video script. Where review
  found a small defect in Bob's code, Claude fixed it in its own commit, with a test.

Material open-source components and third-party services (rules §6.6, §9.3):

| Component | Use | License | Bundled? |
|---|---|---|---|
| Python 3 and its standard library | runtime | PSF-2.0 | no |
| pytest | tests | MIT | no (dev tool) |
| ruff | lint | MIT | no (dev tool) |
| Asterisk | the PBX the adapter talks to | GPL-2.0 | no |
| SpanDSP | the fax modem inside Asterisk's fax module | LGPL-2.1 | no |
| Ghostscript | PDF to fax TIFF, called by the CLI | AGPL-3.0 | no |
| GitHub Pages | hosts the static replay demo | service | no |
| Node.js | runs the page's `app.js` in the static-page test | MIT | no (dev tool) |
| GitHub Actions | CI | service | no |
| Faxbeep | public test inbox for `fax test` | service | no |
| Azure AI Speech | the narration voice in the demo video | service | no |

This repository bundles no third-party code. Its only copyleft code is its own, and the source is
public here. IBM can evaluate or demonstrate the submission without disclosing any proprietary
technology, source code or trade secrets.

## AI-use disclosure

AI tools built most of this, as the rules allow (§8.6). IBM Bob writes most of the code and
tests, and the modernization docs. Claude (Anthropic) built the safety tooling, drives the Bob
runs, reviews each change against the code, fixes the small defects that review finds (each in
its own commit, with a test), and drafted the presentation materials. The demo video's
narration is an AI voice (Azure AI Speech, Dragon HD). Jeffrey reviews the work at two
checkpoints and takes responsibility for the submission (§8.2). No AI tool was given personal,
confidential or restricted information. The baseline was scrubbed first, every Bob prompt passes
the scrub gate, and fixtures use fictional numbers and hosts.

## License

AGPL-3.0-or-later © 2026 Jeffrey Hein. See [LICENSE](LICENSE).
