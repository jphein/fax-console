# Pre-hackathon baseline — unchanged except for scrubbing

This repository's **first commit** (tag `baseline-2026-09-28`) holds the legacy application
exactly as it existed **before** the *Building with IBM Bob* hackathon window opened
(2026-09-28 19:00 ET / 16:00 PDT). Every later commit is new work done during the window.
It follows the Fresh Code Rule (rules §7) and the existing-project clause (§6.5, §6.3.3).

**`legacy/` is frozen.** Nothing under it changes after commit #1. CI enforces that with
`git diff --exit-code baseline-2026-09-28 -- legacy/`. The modernized code lives beside it,
so reviewers can compare the two directly.

## What the legacy application is

A send-only fax service for a house phone system: a Python CLI around Asterisk `SendFax`
over a VoIP.ms SIP trunk, plus the **Fax panel** and the **Asterisk / VoIP.ms status**
code of a single-file, stdlib-only web console that runs on the PBX host. Both ran in
production before the hackathon. The Faxbeep public tester received a page sent through
this path on 2026-09-26/27.

## Sources

All files come from `git show <commit>:<path>` on the owner's private repositories, never
from a working tree. The blob ids are for the **unscrubbed** originals, so a reviewer can
verify them on request (rules §6.5, "reasonable evidence"). Times are PDT.

| Here | Source file | Source commit | Last changed before the window |
|---|---|---|---|
| `legacy/fax/fax/cli.py` | `fax/cli.py` (288 lines) | fax `020a171` | 2026-09-26 22:04 · blob `2d255f9c` |
| `legacy/fax/fax/__init__.py` | `fax/__init__.py` | fax `020a171` | 2026-09-26 22:04 · blob `74aa892c` |
| `legacy/fax/bin/fax` | `bin/fax` | fax `020a171` | 2026-09-26 22:04 · blob `41901663` |
| `legacy/fax/scripts/deploy.sh` | `scripts/deploy.sh` | fax `020a171` | 2026-09-26 22:07 · blob `ebc0d563` |
| `legacy/fax/README.md` | `README.md` | fax `020a171` | 2026-09-27 14:10 · blob `bcbf9c0a` |
| `legacy/fax/CLAUDE.md` | `CLAUDE.md` (agent working notes) | fax `020a171` | 2026-09-26 22:04 · blob `7a5a8ddf` |
| `legacy/fax/docs/route.md` | `docs/route.md` | fax `020a171` | 2026-09-26 22:07 · blob `83beef4c` |
| `legacy/fax/docs/inbound.md` | `docs/inbound.md` (design, never built) | fax `020a171` | 2026-09-27 01:16 · blob `76025a03` |
| `legacy/console/telephony-console.py` | `tools/telephony-console.py`, **excerpt** (see below) | console repo `bd054b0e` (branch `feat/console-fax`) | 2026-09-26 22:04 · blob `ea10c2b0` |
| `LICENSE` | `LICENSE` (AGPL-3.0 text) | fax `020a171` | 2026-09-27 14:10 |

Commit ids in full: fax `020a1719401e2b54d848a7f7c6f6b3259898a170` (2026-09-27 14:28 PDT,
the fax repo's last commit before the window); console `bd054b0e5f644145afc221487ee020b095ab36be`
(2026-09-26 22:04 PDT).

## The console excerpt

The console is an **11,858-line** single file that also runs a private cellular network.
Only the fax and PBX slice is published here: **3,009 source lines are kept verbatim and
8,849 are elided**, in 20 marked gaps. Each gap is one line in the file,
`⋯ [baseline elision: source lines A–B — what was left out] ⋯`, written in whatever comment
syntax is valid at that point (Python, HTML or JS). An 8-line provenance header after the
shebang says the same. The excerpt parses (`python3 -m py_compile`), but it is **not
runnable**: the code still names functions that were elided, just as the original did.

What is kept: the module docstring's design rule, the theme tokens, realm-sigil identity
and `/api/version`, `ast()` (the Asterisk CLI reader), the background-thread registry, the
VoIP.ms credential reader and poller, `read_trunk()`, `read_calls()`, `read_sip_endpoints()`,
the CDR reader with its recordings index, `snapshot()`, the page shell with the *Live state*,
*PSTN account*, *Recent calls* and **Fax** sections and their renderers, the Fax back end
(`fax_cli`, `fax_state`, `_multipart`, `fax_send`), write authentication (`AUTH_JS`,
`write_token`, `write_authorized`), the HTTP handler's PBX and fax routes, and `main`.

| Elided source lines | Lines | What |
|---|---|---|
| 32–57 | 26 | cellular-side handling notes (VTY key material, femtocell DMI console) |
| 476–508 | 33 | voicemail, SMS, core-network and Home Assistant constants |
| 531–536 | 6 | Home Assistant contract constants and the SMS log parser |
| 553–617 | 65 | cellular-core addresses, dialplan-writer regex, handset descriptions, test-extension catalogue |
| 624–700 | 77 | the cellular-core console client |
| 711–1606 | 896 | cellular readers: neighbour lists, TMSI/IMSI attribution, presence, IMSI census, Home Assistant call shaping |
| 2097–3411 | 1315 | Home Assistant contract, cell and ACS state, status collectors, network dependencies, SMS, voicemail, femtocell readers |
| 3510–3624 | 115 | systemd service list and the HLR subscriber reader |
| 3656–3800 | 145 | dialplan reader/writer for inbound ring-group routing |
| 3886–3942 | 57 | directory (HLR joined to handset descriptions) and dialplan globals |
| 3977–8656 | 4680 | SIM/handset inventory, TAC lookup, radio power and band control, the radio and inventory page templates |
| 8998–9091 | 94 | realm navigation bar and section index |
| 9100–9184 | 85 | cellular, voicemail, SMS, inbound-routing, directory and test-extension sections |
| 9234–9625 | 392 | cellular presence, IMSI census, cell-hardware and ACS renderers |
| 9698–9911 | 214 | network-dependency, SMS, voicemail and census renderers; section index |
| 9942–10097 | 156 | services tile; override, ring-picker, directory and test-extension renderers |
| 11180–11209 | 30 | cellular state routes (presence, status, cells, ACS) |
| 11223–11262 | 40 | Home Assistant, network-dependency, SMS, voicemail and census routes |
| 11284–11509 | 226 | matrix, inventory, radio, overview, femtocell, cell and band routes |
| 11600–11796 | 197 | RF and inventory writes (position, band, radio, SIM) and the dialplan save |

The cellular half stays out because it handles subscriber identifiers (IMSI, TMSI, IMEI)
and SIM key material, and it is out of scope for this modernization.

## What scrubbing changed

The hackathon forbids giving personal, confidential or restricted information to AI tools
(§8.6), and this repository is public. So, before any AI tool or GitHub saw the baseline,
identifying values were replaced **mechanically**, by a fixed substitution list kept
outside the repository. Nothing else changed: no reformatting and no fixes.

| Class | Replaced with | Count |
|---|---|---|
| Host names (the PBX host, a workstation, the router) | `pbx`, "the workstation", "the router" | 27 |
| The owner's name or initials | "the owner" | 20 |
| The house phone number (DID) | `202-555-0100` (the fictional 555-01xx block) | 4 |
| A recipient's fax number | `202-555-0142` | 4 |
| LAN IP addresses | `192.0.2.x` (RFC 5737 documentation range, last octet kept) | 3 |
| A reference to a personal filing and its agency | "a real filing", `FORM-1` | 2 |
| The VoIP.ms sub-account id | `000000_house` | 1 |
| A private repository URL | `https://github.com/example/telephony-console` | 1 |
| Cellular-side endpoint names | `cell-core`, `cell-bridge` | 4 |

Kept on purpose:
- **public** test-service numbers: Faxbeep, the demo's destination, and HP's fax test line;
- product, provider and device names (Asterisk, VoIP.ms, OBi100, Canon MX922);
- internal extension numbers such as `2007`, because the code matches on them and they identify no one;
- the copyright line.

**Excluded entirely:**
- `docs/test-page.pdf`: the file at that commit was a personal document. The modernized repo uses a neutral test page written during the window.
- In `docs/inbound.md`, one section about an unrelated house-PBX matter. It is marked as an elision.

`scripts/scrub-check.sh` (commit #2) enforces the scrub on every commit and commit message,
and in CI. It checks generic rules for private IPs, real-looking phone numbers, e-mail
addresses and credential shapes, plus a private deny-list of the real values that is never
committed.

## History of this commit

This commit was rebuilt **once**, on 2026-09-28 at 22:45 PDT, when the repository was under an
hour old and had no forks. The rebuild scrubbed the two cellular-side endpoint names (the row
above), and the tag moved with it. Nothing else changed: the source commits, line ranges and
every other byte are the same. History has not been rewritten since, and will not be; later
fixes go forward in new commits.

The repository itself was recreated on 2026-09-28 at 23:06 PDT, with the same history, to drop
pull-request refs that still pointed at the pre-rewrite commits.

## License

AGPL-3.0-or-later. The fax CLI was relicensed by its owner on 2026-09-27. The console
excerpt is the same owner's code and is released here under the same license.
