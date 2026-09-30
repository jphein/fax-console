# Demo video storyboard (≤ 3 minutes)

Rules §6.3.5 ask for a pre-recorded video, **no longer than three minutes**, on YouTube. The cut runs
**2:21**, under the hard stop at 3:00. Narration is an AI voice: Azure AI Speech, Dragon HD
(`en-US-Andrew:DragonHDLatestNeural`), about 350 words and two minutes of speech. The lines,
subtitles and scene order are in [`narration.mjs`](narration.mjs). Values in double braces come from
[`../deck/slots.json`](../deck/slots.json), filled by [`../deck/fill.py`](../deck/fill.py).

**Two hard rules.** No fax goes to a real recipient: the video shows a dry run, and the one real test
send (to Faxbeep's public test inbox, on 2026-09-27) is cited, not filmed. And no personal data
appears on screen (see the checklist at the end).

Everything on screen comes from a fresh clone of this repository at **e1bb410**. Terminal scenes show
the real output of the commands named, rendered at 100 columns.

## Scenes

| # | At | On screen | Narration (as heard) |
|---|---|---|---|
| 1 | 0:00 | Title card: deck slide 1, dark | **n1** Fax Console. A house phone system's legacy fax tools, modernized with IBM Bob, while the phone line kept working. |
| 2 | 0:09 | The **baseline commit** (tag `baseline-2026-09-28`): a fast scroll of `legacy/console/telephony-console.py` with the label *original 11,858 lines · 3,009 kept here, verbatim · 11 shell-out call sites*; then `legacy/fax/fax/cli.py` with *288 lines · no tests* | **n2** The legacy code is one Python file, nearly 12,000 lines long, and it shells out for every read: to Asterisk, and to a 288-line fax tool with no tests. |
| 3 | 0:21 | Run 1's prompt (`docs/bob-runs/1-analysis.prompt.md`), then `docs/analysis.md` scrolling: the module map, the shell-out table, the migration order. These are the documents, not a Bob replay | **n3** Bob runs headless, inside an operating-system sandbox, and starts with the analysis: a module map, every shell-out, and an order to migrate in. |
| 4 | 0:32 | **Bob fixing one module** ({{module.name}}), replayed from run 5's recording through `scripts/bob-watch.py`, so no live Bob is on camera. The replay's pytest summaries read `1 failed, 176 passed, 5 warnings in 2.08s`, `1 failed, 176 passed in 1.96s`, `3 failed, 186 passed in 1.98s`, then `189 passed in 2.03s`. Then Bob tries `git stash` and the sandbox refuses it: `✗ exit code 1 · read-only file system (150 characters)`. A chip says "replay of run 5 · recorded, sped up" | **n4** Here Bob takes {{module.spoken}}. It pins today's behavior with tests, then fixes the bug review found: an unreadable phone system reported as fine. **n5** The tests go red, then green, before anything is committed. **n5b** Midway, Bob tried git stash. The sandbox's read-only .git refused it, and the owner's work in progress was never at risk. |
| 5 | 0:57 | **The rejection.** Run 5's prompt, item 1 highlighted (`docs/bob-runs/5-faxcli-fixes.prompt.md`: the unquoted ssh command). Then `git diff a64d1c2 7e172ab -- faxcli/transport.py`, cut to `import shlex` and the one line where `" ".join(argv)` becomes `shlex.quote` | **n6** Not everything Bob writes is kept. {{bob.reject_spoken}}. |
| 6 | 1:09 | Terminal: `scripts/test.sh` (the tests and ruff, inside the sandbox) and its summary line; then the green GitHub Actions run for e1bb410, logged out | **n7** {{tests.count}} tests run on recorded fax output, with every number and name replaced. CI runs them on every push. |
| 7 | 1:19 | Deck slide 5 (before and after), with a highlight on the Asterisk adapter | **n8** Before, every panel reached the phone system on its own. Now one adapter is the only way in, and replay mode points it at recorded fixtures instead of the live PBX. |
| 8 | 1:32 | **The demo** at `jphein.github.io/fax-console` (a static replay): recorded state, the account panel (sample data), then the fax log. Then `curl` on the Pages copy of `api/version.json` and on the local replay's `/api/fax/status` | **n9** This is the demo, a static replay of recorded data: the phone system's status, the fax log and the account panel. Nothing on this page can reach a phone line. **n10** Underneath is a small typed API. |
| 9 | 1:47 | **The local replay** at `127.0.0.1:8093` in test mode: the send form (a 555 number, `demo/test-page.pdf`, a throwaway token, the confirm box), then its reply: `replay: nothing is dialled` | **n11** Run locally in test mode, a send comes back as a dry run, and nothing is dialed. The one real test send, to Faxbeep's public test inbox and never to a person, took {{fax.call_seconds}} seconds. |
| 10 | 2:00 | The `docs/bob-usage.md` run ledger and the `Assisted-by: IBM Bob` commit count; then the end card | **n12** The commit log shows Bob wrote {{bob.factor_pct}} of the committed lines, and the Bob usage log lists every run, its cost, and every suggestion we kept or rejected. **n13** Fax Console. Open source under the AGPL. Built with IBM Bob. |

**End card (held about 8 seconds):** Fax Console · github.com/jphein/fax-console · jphein.github.io/fax-console (a
static replay) · AGPL-3.0-or-later · Built with IBM Bob. The small print reads: *Narration is an AI voice
(Azure AI Speech). No fax went to a real recipient. Fixtures use fictional numbers and hosts.* Every
frame also carries a small burned-in line: *Narration: AI voice (Azure AI Speech)*.

## How it is made

1. Fill the slots, then check that `fill.py` reports **0 unfilled** for `narration.mjs`.
2. Render each narration line to audio with Azure AI Speech (Dragon HD), straight to WAV files.
3. Capture from a fresh clone at a pinned commit, headless: terminal scenes are the real command output
   drawn frame by frame at 1920×1080 and 30 fps; browser scenes are headless Chrome with a fresh
   profile. The local replay runs `python3 -m faxconsole --replay tests/fixtures` in a sandboxed
   service that can reach only loopback, and the clone is deleted after capture.
4. Log the text on screen for **every frame** and run it through `scripts/scrub-check.sh`, with a
   planted positive control that must be caught.
5. Mix with ffmpeg. The subtitles (`.srt`) come from `SUB` where it is set, and from the spoken line
   otherwise.
6. Check the runtime (≤ 175 s), have the owner watch the cut, then upload to YouTube as unlisted.

## Before recording: the no-personal-data checklist

- [ ] Record only a **fresh clone of this public repo**, never the private source repositories.
- [ ] No user, host or path in any prompt or window title. Terminal scenes show `$` only.
- [ ] Bob: never live on camera. Replay **run 5 only**: another run's rendered replay must be scanned
      by scrub-check first (run 6's rendered narration shows phone-shaped hits that its raw log does not).
- [ ] Browser: a fresh headless profile with no extensions and no sign-in.
- [ ] Spot-check the fax log: it shows 555 numbers and the public fax test lines only (Faxbeep's and
      HP's, on scrub-check's allowlist of public test services).
- [ ] Never show the live server's `/api/version` (it names the machine); show the Pages copy.
- [ ] The token typed into the send form is a throwaway word, and it is masked.
- [ ] Say "demo" or "static replay", never "live demo", and never call the VoIP.ms balance real: it is sample data.
- [ ] Last pass: step through the finished video scene by scene, looking for numbers, names, hosts and IPs.
