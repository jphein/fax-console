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
  n9:  ["N", "This is the demo, a static replay of recorded data. Status and the fax log are here, and the send form, run locally in test mode, answers without dialing. Nothing here can reach a phone line."],
  n10: ["N", "Underneath is a small typed A P I."],
  n11: ["N", "One real send, to Fax Beep's public test inbox, never to a person. The modernized tool reports it in the same JSON as before."],
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
  n11: "One real send, to Faxbeep's public test inbox, never to a person. The modernized tool reports it in the same JSON as before.",
  n13: "Fax Console. Open source under the AGPL. Built with IBM Bob.",
};

// Scene order, target start times (the recorder recomputes t from real audio lengths) and the shot for each.
export const SCENES = [
  { id: "title",    at: "0:00", lines: ["n1"],         shot: "deck slide 1, dark, 1920x1080" },
  { id: "legacy",   at: "0:09", lines: ["n2"],         shot: "editor on the baseline commit: telephony-console.py scroll, then fax/cli.py; overlay 'original 11,858 lines · 3,009 kept here, verbatim · 11 shell-out call sites', then '288 lines · no tests'" },
  { id: "analysis", at: "0:25", lines: ["n3"],         shot: "Bob Shell in a terminal, its stream rendered by scripts/bob-watch.py: the prompt gate passing, then docs/analysis.md taking shape" },
  { id: "module",   at: "0:37", lines: ["n4", "n5", "n5b"], shot: "Bob fixing {{module.name}}, replayed from run 5 through scripts/bob-watch.py (no live Bob needed): characterization tests red on the unreadable-PBX finding, the fix, green (pytest summaries 1 failed, 3 failed, 189 passed; needs PR #36); then line 835, git stash refused: a red ✗ line cut at \"Unable to create './.git…\", label \"read-only .git\"; 2x speed label" },
  { id: "reject",   at: "1:11", lines: ["n6"],         shot: "docs/bob-runs/5-faxcli-fixes.prompt.md with item 1 highlighted (the unquoted ssh command); then git diff a64d1c2 7e172ab -- faxcli/transport.py, the one line where \" \".join(argv) becomes shlex.quote" },
  { id: "tests",    at: "1:26", lines: ["n7"],         shot: "terminal: {{cmd.test}} summary; then the green GitHub Actions run" },
  { id: "arch",     at: "1:37", lines: ["n8"],         shot: "deck slide 5, dark, with a highlight on the Asterisk adapter" },
  { id: "console",  at: "1:51", lines: ["n9", "n10"],  shot: "browser at jphein.github.io/fax-console (static replay): status, fax log; then the local replay at 127.0.0.1:8093: send form in test mode and its reply, curl /api/fax/status and /api/version" },
  { id: "faxtest",  at: "2:13", lines: ["n11"],        shot: "terminal: fax test --pdf demo/test-page.pdf; cut the call (overlay 'call took {{fax.call_seconds}} s, cut'); JSON result; Faxbeep inbox cropped to the page body" },
  { id: "evidence", at: "2:27", lines: ["n12", "n13"], shot: "the docs/bob-usage.md ledger and the git trailer count (or the Bobalytics Bob factor tile, account and team hidden), then the end card" },
];
export const TARGET_SECONDS = 175; // hard limit 180 (rules §6.3.5)
