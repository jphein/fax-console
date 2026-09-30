# Demo video storyboard (≤ 3 minutes)

Rules §6.3.5 ask for a pre-recorded video, **no longer than three minutes**, on YouTube. The target
is **about 2:49**, with a hard stop at 3:00. Narration is an AI voice: Azure AI Speech, Dragon HD
(`en-US-Andrew:DragonHDLatestNeural`). That is about 340 words, or a little over two minutes of speech.
The lines, subtitles and scene order are in [`narration.mjs`](narration.mjs). Values in double
braces come from [`../deck/slots.json`](../deck/slots.json), filled by
[`../deck/fill.py`](../deck/fill.py).

**Two hard rules.** No fax goes to a real recipient: the one live send is `fax test` to Faxbeep's
public test inbox. And no personal data appears on screen (see the checklist at the end).

## Scenes

| # | At | On screen | Narration (as heard) |
|---|---|---|---|
| 1 | 0:00 | Title card: deck slide 1, dark | **n1** Fax Console. A house phone system's legacy fax tools, modernized with IBM Bob, while the phone line kept working. |
| 2 | 0:09 | Editor on the **baseline commit** (tag `baseline-2026-09-28`): a fast scroll of `legacy/console/telephony-console.py` with the overlay *original 11,858 lines · 3,009 kept here, verbatim · 11 shell-out call sites*; then `legacy/fax/fax/cli.py` with *288 lines · no tests* | **n2** The legacy code is one Python file, nearly 12,000 lines long, and it shells out for every read: to Asterisk, and to a 288-line fax tool with no tests. |
| 3 | 0:25 | Bob Shell in a terminal, its stream rendered by `scripts/bob-watch.py`: the prompt gate passing, then `docs/analysis.md` taking shape | **n3** Bob runs headless, inside an operating-system sandbox, and starts with the analysis: a module map, every shell-out, and an order to migrate in. |
| 4 | 0:37 | **Bob fixing one module** ({{module.name}}), replayed from its recorded run through `scripts/bob-watch.py`, so no live Bob is needed on camera. Characterization tests go red on the unreadable-PBX finding, then Bob's fix, then green. Then run 5's line 835: Bob tries `git stash`, and the sandbox's read-only `.git` refuses it (`Read-only file system`). Shown at 2× with a small label | **n4** Here Bob takes {{module.spoken}}. It pins today's behavior with tests, then fixes the bug review found: an unreadable phone system reported as fine. **n5** The tests go red, then green, before anything is committed. **n5b** Midway, Bob tried git stash. The sandbox's read-only .git refused it, and the owner's work in progress was never at risk. |
| 5 | 1:11 | **The rejection.** Run 5's prompt, item 1 highlighted (`docs/bob-runs/5-faxcli-fixes.prompt.md`: the unquoted ssh command). Then `git diff a64d1c2 7e172ab -- faxcli/transport.py`: the one line where `" ".join(argv)` becomes `shlex.quote` | **n6** Not everything Bob writes is kept. {{bob.reject_spoken}}. |
| 6 | 1:26 | Terminal: `python3 -m pytest -q` and its summary line; then the green GitHub Actions run | **n7** {{tests.count}} tests run on recorded fax output, with every number and name replaced. CI runs them on every push. |
| 7 | 1:37 | Deck slide 5 (before and after), with a highlight on the Asterisk adapter | **n8** Before, every panel reached the phone system on its own. Now one adapter is the only way in, and replay mode points it at recorded fixtures instead of the live PBX. |
| 8 | 1:51 | **The replay console**: status and the fax log (555 numbers) on the Pages demo at `jphein.github.io/fax-console` (a static replay; its send form is disabled); then the local replay at `127.0.0.1:8093` for the send form in test mode and its reply, and `curl` on its `/api/fax/status` and `/api/version` | **n9** This is the demo, a static replay of recorded data. Status and the fax log are here, and the send form, run locally in test mode, answers without dialing. Nothing here can reach a phone line. **n10** Underneath is a small typed API. |
| 9 | 2:13 | Terminal: `fax test --pdf demo/test-page.pdf`, with the call cut (overlay *call took {{fax.call_seconds}} s, cut*) and the JSON result; then the Faxbeep inbox, **cropped to the page body** | **n11** One real send, to Faxbeep's public test inbox, never to a person. The modernized tool reports it in the same JSON as before. |
| 10 | 2:27 | The `docs/bob-usage.md` ledger and the `Assisted-by: IBM Bob` commit count (or the Bobalytics Bob factor tile, with account and team hidden); then the end card | **n12** The commit log shows Bob wrote {{bob.factor_pct}} of the committed lines, and the Bob usage log lists every run, its cost, and every suggestion we kept or rejected. **n13** Fax Console. Open source under the AGPL. Built with IBM Bob. |

**End card (4-second hold):** Fax Console · github.com/jphein/fax-console · jphein.github.io/fax-console (a
static replay) · AGPL-3.0-or-later · Built with IBM Bob. The small print reads: *Narration is an AI voice
(Azure AI Speech). No fax went to a real recipient. Fixtures use fictional numbers and hosts.*

**If Bobalytics turns out to be available on the Pro+ account:** n12 may say "Bobalytics shows…",
and scene 10 shows its Bob factor tile.

## How it is made

1. Fill the slots, then check that `fill.py` reports **0 unfilled** for `narration.mjs`.
2. Render each narration line to audio with Azure AI Speech (Dragon HD). Record the browser scenes
   (1, 7, 8) with Playwright, and screen-record the terminal scenes (2 to 6, 9 and 10) at
   1920×1080, 30 fps.
3. Mix with ffmpeg. The subtitles come from `SUB` where it is set, and from the spoken line
   otherwise.
4. Check the total runtime (≤ 175 s), upload to YouTube as unlisted, and have the owner listen once.

## Before recording: the no-personal-data checklist

- [ ] Record only a **fresh clone of this public repo**, never the private source repositories.
- [ ] Shell: `PS1='$ '`, `HISTFILE=/dev/null`. No user, host or path in the prompt or the window title.
- [ ] Bob: hide the account name, avatar and team. Show only this repo.
- [ ] Browser: a fresh profile with no bookmarks bar, no extensions and no signed-in avatar. The address bar shows `jphein.github.io/fax-console/` for the Pages shots and `127.0.0.1:8093` for the local send.
- [ ] Spot-check the replay console's fax log: 555 numbers and `example.com` hosts only.
- [ ] `fax test`: run `fax test --dry-run` first and read its output. It must show no house number, station ID, account or internal host. If any appears, mask it in the CLI or blur it in the edit.
- [ ] Send `demo/test-page.pdf`, which carries no personal information. The Faxbeep inbox is **public**.
- [ ] Faxbeep page: the header line a fax machine stamps can carry the sender's station ID. Send one `fax test` before filming and look at the received page. Crop the header line and any sender number out of frame.
- [ ] Bobalytics, if shown: KPI tiles only, with account and team names hidden.
- [ ] Last pass: step through the finished video scene by scene, looking for numbers, names, hosts and IPs.
