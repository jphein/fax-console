// Narration for the Fax Console demo video, in the shape record.mjs already uses
// (L = {id: [voice, text]} for the text-to-speech step, SUB = on-screen subtitle text).
// Double-brace slots come from slots.json: run `fill.py slots.json narration.mjs build/narration.mjs`
// and render only when fill.py reports 0 unfilled.
// L holds the text as spoken (acronyms spelled for the ear); SUB holds the subtitle text.

export const VOICE = { N: "en-US-Andrew:DragonHDLatestNeural" }; // Azure AI Speech, Dragon HD

export const L = {
  n1:  ["N", "Fax Console. A house phone system's legacy fax tools, modernized with I B M Bob, while the phone line kept working."],
  n2:  ["N", "The legacy code is one Python file, nearly twelve thousand lines long, and it shells out for every read: to Asterisk, and to a two hundred and eighty-eight line fax tool with no tests."],
  n3:  ["N", "Bob runs headless, inside an operating-system sandbox, and starts with the analysis: a module map, every shell-out, and an order to migrate in."],
  n4:  ["N", "Here Bob takes {{module.spoken}}. It pins today's behavior with tests, then fixes the bug review found: an unreadable phone system reported as fine."],
  n5:  ["N", "The tests go red, then green, before anything is committed."],
  n5b: ["N", "Midway, Bob tried git stash. The sandbox's read-only git folder refused it, and the owner's work in progress was never at risk."],
  n6:  ["N", "Not everything Bob writes is kept. {{bob.reject_spoken}}."],
  n7:  ["N", "{{tests.count}} tests run on recorded fax output, with every number and name replaced. C I runs them on every push."],
  n8:  ["N", "Before, every panel reached the phone system on its own. Now one adapter is the only way in, and replay mode points it at recorded fixtures instead of the live P B X."],
  n9:  ["N", "This is the demo, a static replay of recorded data: the phone system's status, the fax log and the account panel. Nothing on this page can reach a phone line."],
  n10: ["N", "Underneath is a small typed A P I."],
  n11: ["N", "Run locally in test mode, a send comes back as a dry run, and nothing is dialed. The one real test send, to Fax Beep's public test inbox and never to a person, took {{fax.call_seconds}} seconds."],
  n12: ["N", "The commit log shows Bob wrote {{bob.factor_pct}} of the committed lines, and the Bob usage log lists every run, its cost, and every suggestion we kept or rejected."],
  n13: ["N", "Fax Console. Open source under the A G P L. Built with I B M Bob."],
};

export const SUB = {
  n1:  "Fax Console. A house phone system's legacy fax tools, modernized with IBM Bob, while the phone line kept working.",
  n2:  "The legacy code is one Python file, nearly 12,000 lines long, and it shells out for every read: to Asterisk, and to a 288-line fax tool with no tests.",
  n4:  "Here Bob takes {{module.name}}. It pins today's behavior with tests, then fixes the bug review found: an unreadable phone system reported as fine.",
  n5b: "Midway, Bob tried git stash. The sandbox's read-only .git refused it, and the owner's work in progress was never at risk.",
  n7:  "{{tests.count}} tests run on recorded fax output, with every number and name replaced. CI runs them on every push.",
  n8:  "Before, every panel reached the phone system on its own. Now one adapter is the only way in, and replay mode points it at recorded fixtures instead of the live PBX.",
  n10: "Underneath is a small typed API.",
  n11: "Run locally in test mode, a send comes back as a dry run, and nothing is dialed. The one real test send, to Faxbeep's public test inbox and never to a person, took {{fax.call_seconds}} seconds.",
  n13: "Fax Console. Open source under the AGPL. Built with IBM Bob.",
};

// Scene order, target start times (the recorder recomputes t from real audio lengths) and the shot for each.
export const SCENES = [
  { id: "title",    at: "0:00", lines: ["n1"],         shot: "deck slide 1, dark, 1920x1080" },
  { id: "legacy",   at: "0:09", lines: ["n2"],         shot: "editor on the baseline commit: telephony-console.py scroll, then fax/cli.py; overlay 'original 11,858 lines · 3,009 kept here, verbatim · 11 shell-out call sites', then '288 lines · no tests'" },
  { id: "analysis", at: "0:21", lines: ["n3"],         shot: "docs/bob-runs/1-analysis.prompt.md (the analysis prompt), then docs/analysis.md scrolling: the module map, the shell-out table, the migration order (documents, not a Bob replay: only run 5 is replayed on camera)" },
  { id: "module",   at: "0:32", lines: ["n4", "n5", "n5b"], shot: "run 5 replayed through scripts/bob-watch.py (no live Bob): pytest summaries 1 failed, 176 passed, 5 warnings -> 1 failed, 176 passed -> 3 failed, 186 passed -> 189 passed; then git stash refused: \"✗ exit code 1 · read-only file system (150 characters)\"; chip \"replay of run 5 · recorded, sped up\"" },
  { id: "reject",   at: "0:57", lines: ["n6"],         shot: "docs/bob-runs/5-faxcli-fixes.prompt.md with item 1 highlighted (the unquoted ssh command); then git diff a64d1c2 7e172ab -- faxcli/transport.py, the one line where \" \".join(argv) becomes shlex.quote" },
  { id: "tests",    at: "1:09", lines: ["n7"],         shot: "terminal: scripts/test.sh -q (the sandboxed test run) and its summary line; then the green GitHub Actions run, logged out" },
  { id: "arch",     at: "1:19", lines: ["n8"],         shot: "deck slide 5, dark, with a highlight on the Asterisk adapter" },
  { id: "console",  at: "1:32", lines: ["n9", "n10"],  shot: "the Pages demo at jphein.github.io/fax-console (a static replay): status, fax log, account panel; then curl on the Pages copy of api/version.json and the local replay\'s /api/fax/status (127.0.0.1:8093)" },
  { id: "faxtest",  at: "1:47", lines: ["n11"],        shot: "the local replay at 127.0.0.1:8093: the send form in test mode (a 555 number, demo/test-page.pdf, a throwaway token, confirm), then its dry-run JSON reply: dry_run true, replay: nothing is dialled" },
  { id: "evidence", at: "2:00", lines: ["n12", "n13"], shot: "the docs/bob-usage.md ledger and the git trailer count, then the end card" },
];
export const TARGET_SECONDS = 175; // hard limit 180 (rules §6.3.5)
