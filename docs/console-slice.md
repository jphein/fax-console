# Console-slice map, keyed to the baseline excerpt

Week-2 brief: what the extraction of the Fax panel and the Asterisk/VoIP.ms status code touches, so it
is a plan and not a discovery. Written by Lucid on 2026-09-28.

- **What it covers:** `legacy/console/telephony-console.py` at the baseline tag (`37ac5e9`, 3,037 lines), the excerpt in this repo.
- **Two numberings in every row:**
  - `e:` is a line in that excerpt. It is what you edit and grep.
  - `s:` is the same line in the private original the excerpt was cut from. The team keeps it for
    cross-reference; you can ignore it.
  - `≈` marks a line with no exact twin (it borrows the nearest mapped line above).
- **How it was made:**
  - It is derived from the excerpt's syntax tree, not by eye.
  - Dependencies count references as well as calls, which catches thread targets and dispatch dicts.
  - The slice is the closure from the PBX routes, the Asterisk and fax-CLI seams, their callers, and the
    VoIP.ms and fax names.
- **Alignment check:** 20 elision markers. 3,009 excerpt lines map one-to-one to the original
  (21 of them with a value scrubbed in place). No other line was added or dropped,
  and every marker's neighbours match the source range it states.
- **Elided names:** the excerpt references some names that it does not define (its header says so). §3 lists
  the ones the slice touches. Treat them as outside interfaces: stub them, or drop the calls.

## Summary
- **The slice is 19 functions and methods, 518 lines of Python** (out of 41 in the
  excerpt), plus the PBX pieces of the `PAGE` template (§7).
- **Entry points:** `GET /api/voipms`, `GET /api/fax`, `POST /api/fax/send`.
- **Tags:**
  - 12 PBX-ONLY: move as is.
  - 4 SHARED: also used by other code in the excerpt; split them, or keep a copy.
  - 2 GENERIC: utilities; copy them.
  - 1 MIXED: they call elided code; keep the PBX half and stub the rest (§3, §8).
- **Seams:**
  - 2 process seams: `ast()`, `fax_cli()`.
  - Network seams: `VoipMsPoller._call` (urllib.request.Request, urllib.request.urlopen).

## 1. Entry points (routes in `H`, the `BaseHTTPRequestHandler`)

| method | route | branch lines | direct callees | shells out inline |
|---|---|---|---|---|
| GET | `/api/voipms` | e:2859–2861 · s:11220–11222 | `H._send`, `VOIPMS` | no |
| GET | `/api/fax` | e:2885–2886 · s:11510–11511 | `H._send`, `fax_state` | no |
| POST | `/api/fax/send` | e:2958–2974 · s:11583–11599 | `H._send`, `_multipart`, `fax_send` | no |

HTTP-layer methods these routes use (not slice; the new service has its own): `H._send` (e:2708–2726 · s:11040–11058).

**Other routes in the excerpt whose closure reaches into the slice** (keep them working or re-point them):

| method | route | branch lines | slice functions reached |
|---|---|---|---|
| GET | `/api/state` | e:2835–2839 · s:11167–11171 | `ast`, `read_calls`, `read_sip_endpoints`, `read_trunk` |

## 2. Slice functions and methods

Sorted by line. **Globals:** R means read; W means assigned via `global`, or mutated by subscript or container
methods. **Refs** are functions passed by name (not called).

| tag | name | lines | size | calls | refs | globals R | globals W | shell | net |
|---|---|---|---|---|---|---|---|---|---|
| SHARED | `ast` | e:507–514 · s:701–708 | 8 | — | — | — | — | 1 | — |
| SHARED | `start_background` | e:567–589 · s:1656–1678 | 23 | — | — | `BACKGROUND_THREADS` | — | — | — |
| PBX-ONLY | `_voipms_scrub` | e:681–712 · s:1770–1801 | 32 | — | — | — | — | — | — |
| PBX-ONLY | `_voipms_creds` | e:715–757 · s:1804–1846 | 43 | — | — | `VOIPMS_ENV` | — | — | — |
| GENERIC | `VoipMsPoller.__init__` | e:782–811 · s:1871–1900 | 30 | `VoipMsPoller._load` | — | — | — | — | — |
| PBX-ONLY | `VoipMsPoller._load` | e:813–835 · s:1902–1924 | 23 | — | — | `VOIPMS_CACHE_FILE`, `VOIPMS_LEGACY_CACHE` | — | — | — |
| PBX-ONLY | `VoipMsPoller._save` | e:837–845 · s:1926–1934 | 9 | — | — | `VOIPMS_CACHE_FILE`, `VOIPMS_STATE_DIR` | — | — | — |
| PBX-ONLY | `VoipMsPoller._call` | e:847–867 · s:1936–1956 | 21 | `_voipms_scrub` | — | `VOIPMS_API`, `VOIPMS_UA` | — | — | `urllib.request.Request`, `urllib.request.urlopen` |
| PBX-ONLY | `VoipMsPoller._refresh_once` | e:869–954 · s:1958–2043 | 86 | `VoipMsPoller._call`, `VoipMsPoller._save`, `_voipms_creds`, `_voipms_scrub` | — | `VOIPMS_ENV`, `VOIPMS_INTERVALS`, `VOIPMS_SUBACCOUNT` | — | — | — |
| PBX-ONLY | `VoipMsPoller._loop` | e:956–965 · s:2045–2054 | 10 | `VoipMsPoller._refresh_once` | — | — | — | — | — |
| PBX-ONLY | `VoipMsPoller.start` | e:968–975 · s:2057–2064 | 8 | `start_background` | `VoipMsPoller._loop` | — | — | — | — |
| PBX-ONLY | `VoipMsPoller.snapshot` | e:977–1003 · s:2066–2092 | 27 | — | — | `VOIPMS_LOW_BALANCE`, `VOIPMS_STALE_AFTER` | — | — | — |
| SHARED | `read_trunk` | e:1009–1021 · s:3412–3424 | 13 | `ast` | — | — | — | — | — |
| MIXED | `read_calls` | e:1024–1104 · s:3427–3507 | 81 | `ast` | — | — | — | — | — |
| SHARED | `read_sip_endpoints` | e:1108–1136 · s:3625–3653 | 29 | `ast` | — | — | — | — | — |
| PBX-ONLY | `fax_cli` | e:2010–2027 · s:10342–10359 | 18 | — | — | `FAX_CLI` | — | 1 | — |
| PBX-ONLY | `fax_state` | e:2030–2037 · s:10362–10369 | 8 | `fax_cli` | — | `FAX_CLI`, `FAX_INBOX` | — | — | — |
| GENERIC | `_multipart` | e:2040–2055 · s:10372–10387 | 16 | — | — | — | — | — | — |
| PBX-ONLY | `fax_send` | e:2058–2090 · s:10390–10422 | 33 | `fax_cli` | — | `FAX_INBOX`, `FAX_MAX_BYTES` | — | — | — |

## 3. Elided names the slice references

These are defined in the original but not in the excerpt. The marker line (`e:`) says what was left out there.

| name | kind | referenced by (e: lines) | defined at | elision marker |
|---|---|---|---|---|
| `MSC_VTY` | global | `read_calls` e:1049 | s:553 (re-assigned at s:4117) | e:499 (s:553–617), e:1260 (s:3977–8656) |
| `vty` | function | `read_calls` e:1049 | s:627–698 | e:506 (s:624–700) |

## 4. Shell-out inventory (slice and PBX routes)

Argument shapes are abstracted: literals that are not plain command words show as `<str>`.

| function | line | api | argv shape | shell=True | timeout | used by |
|---|---|---|---|---|---|---|
| `ast` | e:510 · s:704 | `subprocess.run` | `[asterisk, -rx, <expr>]` | no | `timeout` | `read_calls`, `read_sip_endpoints`, `read_trunk` |
| `fax_cli` | e:2013 · s:10345 | `subprocess.run` | `[<expr>, --local, --json, <expr>]` | no | `timeout` | `fax_send`, `fax_state` |

**Asterisk CLI commands behind `ast()`** (its full command surface; leading command words only):

| caller | line | command |
|---|---|---|
| `read_trunk` | e:1011 · s:3414 | `pjsip show registrations` |
| `read_calls` | e:1032 · s:3435 | `core show channels` |
| `read_sip_endpoints` | e:1112 · s:3629 | `pjsip show endpoints` |

## 5. Threads, background work and startup wiring

| where | line | api | target | in slice? |
|---|---|---|---|---|
| `start_background` | e:587 · s:1676 | `threading.Thread` | `target` | yes |
| `snapshot` | e:1229 · s:3946 | `ThreadPoolExecutor` | `—` | no |
| `VoipMsPoller.start` → `start_background` | e:975 · s:2064 | thread launcher | `self._loop` | yes |
| `__main__` → `start_background` | e:3020 · s:11841 | thread launcher | `_s.serve_forever` (`'listener'`) | no |

Singletons of slice classes: `VOIPMS` = `VoipMsPoller(…)` at e:1006 · s:2095.

Startup (`__main__` block) calls that wire the slice: `VOIPMS.start` (e:3026 · s:11847), `srv.serve_forever` (e:3037 · s:11858), `ThreadingHTTPServer` (e:2981 · s:11802), `start_background` (e:3020 · s:11841), `ThreadingHTTPServer` (e:2990 · s:11811), `ThreadingHTTPServer` (e:3013 · s:11834).

## 6. Module globals the slice touches (config, state, caches, locks)

"defined" is `elided` when only the original defines the global: the excerpt reads a name it does not set.

| global | defined | kind | slice R | slice W | outside R | outside W |
|---|---|---|---|---|---|---|
| `VOIPMS_API` | e:461 · s:510 | `str` | 1 | 0 | 0 | 0 |
| `VOIPMS_UA` | e:462 · s:511 | `str` | 1 | 0 | 0 | 0 |
| `VOIPMS_ENV` | e:468 · s:517 | `str` | 2 | 0 | 0 | 0 |
| `VOIPMS_SUBACCOUNT` | e:469 · s:518 | `str` | 1 | 0 | 0 | 0 |
| `VOIPMS_INTERVALS` | e:470 · s:519 | `Dict` | 1 | 0 | 0 | 0 |
| `VOIPMS_LOW_BALANCE` | e:471 · s:520 | `float` | 1 | 0 | 0 | 0 |
| `VOIPMS_STALE_AFTER` | e:472 · s:521 | `int` | 1 | 0 | 0 | 0 |
| `VOIPMS_STATE_DIR` | e:473 · s:522 | `call:os.environ.get` | 1 | 0 | 0 | 0 |
| `VOIPMS_CACHE_FILE` | e:474 · s:523 | `call:os.path.join` | 2 | 0 | 0 | 0 |
| `VOIPMS_LEGACY_CACHE` | e:480 · s:529 | `str` | 1 | 0 | 0 | 0 |
| `BACKGROUND_THREADS` | e:540 · s:1629 | `Dict` | 1 | 0 | 1 | 0 |
| `FAX_CLI` | e:2005 · s:10337 | `str` | 2 | 0 | 0 | 0 |
| `FAX_INBOX` | e:2006 · s:10338 | `call:os.path.join` | 2 | 0 | 0 | 0 |
| `FAX_MAX_BYTES` | e:2007 · s:10339 | `BinOp` | 1 | 0 | 1 | 0 |
| `MSC_VTY` | elided (s:553, s:4117) | `Tuple` | 1 | 0 | 0 | 0 |

**Globals used on both sides of the slice in the excerpt** (a new service needs its own copy or an interface): `BACKGROUND_THREADS`, `FAX_MAX_BYTES`.

## 7. Front end: PBX pieces inside the templates

**JS functions with PBX content**, ordered by line; "hits" are the PBX words and routes each one contains:

| template | line | JS function | hits |
|---|---|---|---|
| `PAGE` | e:1655 · s:9228 | `prov` | `voipms_seen` |
| `PAGE` | e:1663 · s:9627 | `renderVoipms` | `asterisk`, `registration`, `trunk`, `voipms`, `voipms_seen` |
| `PAGE` | e:1724 · s:9688 | `loadVoipms` | `/api/voipms`, `voipms`, `voipms_seen` |
| `PAGE` | e:1735 · s:9912 | `tileTrunk` | `registration`, `trunk` |
| `PAGE` | e:1747 · s:9924 | `tileCalls` | `asterisk` |
| `PAGE` | e:1767 · s:10099 | `renderCdr` | `fax` |
| `PAGE` | e:1799 · s:10131 | `renderFax` | `/api/fax`, `asterisk`, `fax`, `faxes`, `faxlog`, `trunk` |
| `PAGE` | e:1837 · s:10169 | `loadFax` | `/api/fax` |
| `PAGE` | e:1841 · s:10173 | `onclick` | `/api/fax/send`, `asterisk`, `fax`, `faxconfirm`, `faxfile`, `faxlabel` |
| `PAGE` | e:1897 · s:10229 | `load` | `trunk` |

**PBX route strings in the templates** (fetch, XHR, form actions and so on):

| template | line | route | inside JS function |
|---|---|---|---|
| `PAGE` | e:1725 · s:9689 | `/api/voipms` | `loadVoipms` |
| `PAGE` | e:1802 · s:10134 | `/api/fax` | `renderFax` |
| `PAGE` | e:1838 · s:10170 | `/api/fax` | `loadFax` |
| `PAGE` | e:1839 · s:10171 | `/api/fax` | `loadFax` |
| `PAGE` | e:1853 · s:10185 | `/api/fax/send` | `onclick` |

**HTML element ids:** `voipms` (e:1610 · s:9099), `fax` (e:1615 · s:9188), `faxform` (e:1618 · s:9191), `faxnum` (e:1619 · s:9192), `faxlabel` (e:1621 · s:9194), `faxfile` (e:1622 · s:9195), `faxconfirm` (e:1623 · s:9196), `faxsend` (e:1625 · s:9198), `faxmsg` (e:1626 · s:9199), `faxlog` (e:1642 · s:9215).

Templates: `TOKENS_CSS` e:62–277 · s:79–294 (12,428 chars), `PAGE` e:1261–1989 · s:8657–10321 (42,551 chars), `AUTH_JS` e:2125–2527 · s:10457–10859 (17,785 chars).

## 8. Boundary with the rest of the excerpt (the split list)

**Functions outside the slice that call or reference slice functions.** The extraction must re-point these,
or keep copies:

| outside function | lines | uses slice functions |
|---|---|---|
| `snapshot` | e:1226–1250 · s:3943–3967 | `read_calls`, `read_sip_endpoints`, `read_trunk` |

**MIXED slice functions.** They call elided code, so keep the PBX half and stub or drop the elided calls:

| function | lines | elided names it calls | elided globals it reads |
|---|---|---|---|
| `read_calls` | e:1024–1104 · s:3427–3507 | `vty` | `MSC_VTY` |

**For the team (s: only):** slice functions that elided code in the original also calls. Bob can ignore this:

| function | e: lines | callers in the original that the excerpt elides |
|---|---|---|
| `read_trunk` | e:1009–1021 · s:3412–3424 | 1 (s:2688) |
| `read_sip_endpoints` | e:1108–1136 · s:3625–3653 | 2 (s:2597, s:2688) |

## 9. Suggested extraction order (leaf first)

1. `ast` (SHARED), `start_background` (SHARED), `_voipms_scrub` (PBX-ONLY), `_voipms_creds` (PBX-ONLY), `VoipMsPoller._load` (PBX-ONLY), `VoipMsPoller._save` (PBX-ONLY), `VoipMsPoller.snapshot` (PBX-ONLY), `fax_cli` (PBX-ONLY), `_multipart` (GENERIC)
2. `VoipMsPoller.__init__` (GENERIC), `VoipMsPoller._call` (PBX-ONLY), `read_trunk` (SHARED), `read_calls` (MIXED), `read_sip_endpoints` (SHARED), `fax_state` (PBX-ONLY), `fax_send` (PBX-ONLY)
3. `VoipMsPoller._refresh_once` (PBX-ONLY)
4. `VoipMsPoller._loop` (PBX-ONLY)
5. `VoipMsPoller.start` (PBX-ONLY)

## 10. Seams for step 7
- **`ast()`** (e:507–514 · s:701–708) is the only shell-out on its path. Every user goes through it:
  `read_calls`, `read_sip_endpoints`, `read_trunk`. One adapter with a replay mode covers them all.
- **`fax_cli()`** (e:2010–2027 · s:10342–10359) is the only shell-out on its path. Every user goes through it:
  `fax_send`, `fax_state`. One adapter with a replay mode covers them all.
- **Network clients in the slice:** `VoipMsPoller._call` (urllib.request.Request, urllib.request.urlopen).
  The VoIP.ms REST client needs a fixture or replay mode, so the public demo never calls VoIP.ms.
- **The one background thread** is the VoIP.ms poller (`VoipMsPoller._loop`, `VoipMsPoller.start`).
  The extracted service owns its lifecycle.
- **The MIXED functions (§8):** keep their PBX half, and put the elided calls behind a stub.

## 11. What the original's slice has that the excerpt leaves out

These are parts of the full slice that the excerpt does not carry, so they are out of scope for the
build. Each row names only the marker line that stands in for it; the marker itself says what was left out.

| what | s: lines | elision marker |
|---|---|---|
| a slice function | s:3129–3216 | e:1008 |
| a GET route | s:11241–11246 | e:2862 |
| a JS function | s:6966 | e:1260 |
| a JS function | s:9243 | e:1661 |
| a JS function | s:9557 | e:1661 |
| a JS function | s:9620 | e:1661 |
| a JS function | s:9844 | e:1734 |
| a JS function | s:9854 | e:1734 |
| a JS function | s:9892 | e:1734 |
| a JS function | s:9954 | e:1765 |
| a JS function | s:9973 | e:1765 |
| a JS function | s:10011 | e:1765 |
| a JS function | s:10026 | e:1765 |

