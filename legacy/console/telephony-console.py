#!/usr/bin/env python3
# ─── fax-console pre-hackathon baseline ─────────────────────────────────────
# EXCERPT of tools/telephony-console.py from the owner's private repository,
# commit bd054b0e (2026-09-26 22:04 PDT), written before the hackathon window. Only the Fax
# panel and the Asterisk/VoIP.ms status code are kept; every gap is marked
# "baseline elision" with its source line range and what was left out.
# Identifying values are scrubbed (BASELINE.md lists the classes). Otherwise
# unchanged. Not runnable on its own: elided names are referenced as they were.
# ─────────────────────────────────────────────────────────────────────────────
"""telephony-console -- the control surface for the house phone network.

Runs on `pbx`. One page that shows what the network is actually doing and
lets the owner change the parts that are safe to change from a browser:

  * live state  -- femtocell, PSTN trunk, active calls, core services
  * inbound routing -- which handsets ring on an inbound PSTN call (WRITES config)
  * directory   -- every extension, what it is, and where that claim comes from
  * test extensions -- *43 / *44 / *46 / *60 / *97 / *98, documented in place
  * recent calls -- the CDR, joined to its recordings, playable in the page

================================================================================
 THE ONE RULE THIS FILE EXISTS TO ENFORCE
================================================================================
 NEVER RENDER A STATE YOU CANNOT ACTUALLY READ.

 "not probed" is a fine thing to show. A wrong green dot is not -- it is worse
 than showing nothing, because it is believed.

 The specific trap, already paid for once:
   `pjsip show contacts` reports EVERY CELLULAR HANDSET AS ABSENT, because they
   attach through the MSC and are not PJSIP contacts at all. A first version of
   this console's predecessor showed all five as "no contact" -- confidently
   wrong. Cellular rows in this file therefore NEVER get a presence dot. They
   get an explanation.

 Consequently every live value on the page carries the command that produced
 it, visible on demand, so any reading can be audited back to its source.
================================================================================

 ⋯ [baseline elision: source lines 32–57 — cellular-side handling notes (VTY key material, femtocell DMI console)] ⋯

 WHY A SEPARATE SERVICE: web/exchange-status.py is a 2500-line production
 dashboard and it is the board that reports whether the network is up. Adding a
 config writer to it risks the one instrument we would need if something breaks.
 This is self-contained and can be deleted without touching anything else.
"""
import csv, hmac, io, json, os, platform, re, shutil, socket, subprocess, sys, threading, time
import urllib.parse, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# Shared theme tokens, interpolated into BOTH pages this file serves.
#
# ⚠️ ONE marker pair per file: scripts/sync-tokens.sh matches the FIRST one, so a
# second block would sit permanently unchecked while the checker reported the
# file as "ok" -- a green light that hides what it is not looking at. Both the
# console and the SIM ledger substitute __TOKENS__ from this single constant,
# and __STATUS__ from STATUS_CSS the same way.
# ---------------------------------------------------------------------------
TOKENS_CSS = r"""/* realm-tokens:begin — synced from web/realm-tokens.css by scripts/sync-tokens.sh */
:root{
  /* --- ground & paper ---------------------------------------------------- */
  --bg:#f4efe4;          /* page ground — warm paper                          */
  --bg2:#fbf8f1;         /* raised ground, gradients, code wells              */
  --panel:#fffdf8;       /* card / panel face                                 */

  /* --- ink --------------------------------------------------------------- */
  --ink:#241f18;         /* body text                                         */
  --ink2:#5c5244;        /* secondary text, labels                            */

  /* --- rules ------------------------------------------------------------- */
  --line:#ddd0b8;        /* ordinary hairline                                 */
  --line2:#c6b494;       /* emphasised rule — STRONGER than --line            */

  /* --- brass: the accent ------------------------------------------------- */
  --brass:#8a6222;       /* links, accents, the identity colour               */
  --brass2:#a97c31;      /* hover / secondary brass                           */
  --brass-soft:#efe0c0;  /* brass wash for chips and fills                    */

  /* --- state: the three-verdict vocabulary -------------------------------
     Used identically by the console's presence column and the SIM ledger's
     verdict chips, because they are THE SAME THREE STATES:
       ok    read, and correct        (filled mark)
       bad   read, and wrong          (filled mark, oxide)
       idle  NOT READ / not probed    (HOLLOW mark — never a default green)
     Colour is never the only carrier: every state pairs its mark with a WORD,
     so the vocabulary survives greyscale and colour-blindness.            */
  --ok:#2f6b41;   --ok-bg:#e2efe4;
  --warn:#8a5a12; --warn-bg:#f6e9d2;
  --bad:#9c2f26;  --bad-bg:#f7e2df;
  --idle:#6b6355; --idle-bg:#ece5d8;

  /* --- staleness: MEASURED, BUT NOT NOW ----------------------------------
     The fourth state, and the one this palette was missing. `idle` means NOT
     READ. `stale` means read, correctly, at a time that is no longer now --
     a distinction the surfaces had no way to draw, so a value measured once
     at 03:00 rendered identically to one measured a second ago.
     A stale mark must ALWAYS carry its age in the same breath ("last read
     4m ago"); a bare dot re-creates the exact ambiguity it exists to remove. */
  --stale:#7a6a3f;  --stale-bg:#f2ead6;

  /* --- call direction ---------------------------------------------------- */
  --in:#2b5f7a;          /* inbound                                           */
  --out:#6a4a86;         /* outbound                                          */

  /* --- (+) additions the other surfaces need ----------------------------- */
  --line-soft:#e8dcc6;   /* (+) lighter than --line, for dense table rows     */
  --code-bg:#f0ead9;     /* (+) inline code and pre wells                     */
  --radius:10px;         /* (+) one corner radius everywhere                  */
  --radius-sm:6px;       /* (+) chips, code, small controls                   */

  --shadow:0 1px 2px rgba(60,45,20,.10), 0 8px 24px -12px rgba(60,45,20,.30);

  /* --- spacing: ONE 4px scale, so seven surfaces stop improvising -------- */
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px;

  /* --- type scale: the two FACES already existed; the SIZES did not ------
     Sizes were being picked per surface (13.5px, 12.5px, 11.5px, .82rem ...),
     which is the same drift the palette had, in a dimension nobody watched.
     No new font files and no CDN -- the stacks below stay local by design. */
  --t-xs:11px;   /* mono labels, letterspaced uppercase                     */
  --t-sm:13px;   /* chips, table cells, secondary text                      */
  --t-md:15px;   /* body                                                    */
  --t-lg:18px;   /* panel headings                                          */
  --t-xl:24px;   /* page title                                              */
  --lh-tight:1.25; --lh:1.5;

  /* --- type: two faces, no CDN -------------------------------------------
     :8080 uses serif + mono only, with letterspaced uppercase mono for labels
     instead of a third face. Adopting that drops the Archivo/Source Serif 4
     Google Fonts dependency the two doc pages currently carry -- local pages
     should not need the network to look right.                            */
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Times New Roman",serif;
  --mono:"SF Mono",ui-monospace,"JetBrains Mono","DejaVu Sans Mono",Menlo,Consolas,monospace;
}

@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#101317; --bg2:#151920; --panel:#181d24;
    --ink:#e8e2d4; --ink2:#9aa0a6;
    --line:#2a313a; --line2:#3a434e;
    --brass:#d9ad5c; --brass2:#c9973f; --brass-soft:#2b2418;
    --ok:#6fcf8f;   --ok-bg:#16281c;
    --warn:#e0b062; --warn-bg:#2a2114;
    --bad:#f2867a;  --bad-bg:#2c1917;
    --idle:#7d8590; --idle-bg:#1d232b;
    --stale:#c2b184; --stale-bg:#241f14;
    --in:#7fc2e8;   --out:#c2a4e8;
    --line-soft:#232a32;
    --code-bg:#131820;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 30px -14px rgba(0,0,0,.7);
  }
}

/* An explicit choice wins in both directions. Every colour is defined on bare
   :root first, so nothing has its ONLY definition inside a media query. */
:root[data-theme="dark"]{
  --bg:#101317; --bg2:#151920; --panel:#181d24;
  --ink:#e8e2d4; --ink2:#9aa0a6;
  --line:#2a313a; --line2:#3a434e;
  --brass:#d9ad5c; --brass2:#c9973f; --brass-soft:#2b2418;
  --ok:#6fcf8f;   --ok-bg:#16281c;
  --warn:#e0b062; --warn-bg:#2a2114;
  --bad:#f2867a;  --bad-bg:#2c1917;
  --idle:#7d8590; --idle-bg:#1d232b;
  --stale:#c2b184; --stale-bg:#241f14;
  --in:#7fc2e8;   --out:#c2a4e8;
  --line-soft:#232a32;
  --code-bg:#131820;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 30px -14px rgba(0,0,0,.7);
}

/* ---- MOBILE, added 2026-09-07 ----------------------------------------
   Lives in the TOKEN SOURCE so every surface gets it from one edit --
   status, console, radio, matrix, inventory, build-guide, runbooks,
   sources. Adding it per-page is how six of them end up slightly
   different.
   The specific fault it fixes: /runbooks renders ELEVEN tables and only
   three sat in a scrolling box, so on a phone the widest table set the
   width of the document and every other section inherited a sideways
   scroll. `display:block; overflow-x:auto` on the table itself is the
   CSS-only fix -- each table scrolls in its own box, the body does not.
   Scoped to narrow screens ON PURPOSE: on a desktop `display:table` is
   what makes columns line up, and changing it there would be a
   regression introduced to fix a problem that only exists at 400px. */
@media (max-width:760px){
  body{overflow-x:hidden}
  table{display:block;max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}
  pre,code{white-space:pre-wrap;word-break:break-word}
  img,svg{max-width:100%;height:auto}
}
@media (max-width:420px){ body{font-size:14px} }

/* === ABSENCE — SIX meanings, and a VOCABULARY PRIMITIVE, which is why it lives
   here and not in `realm-status`. Any surface that renders a value can have an
   absent one, so making this optional meant 224 undifferentiated em dashes on
   two surfaces. Moved 2026-09-12 at lucid-console154's reading, which was right:
   "if the matrix is the first non-console surface to need it, that is evidence
   it is a token, not a status thing."
   ⚠️ The `rs-` prefix is kept deliberately — renaming would churn every call
   site for a cosmetic gain, and the family still reads as one vocabulary even
   though it now ships in two blocks. === */
.rs-absent{color:var(--idle);font-style:italic}
/* ⛔ NO GLYPH FROM CSS WHEN THE CELL HAS ONE. This block used to emit an em dash
   via ::after while the matrix wrote ⊘ in the markup -- TWO GLYPHS FOR ONE
   MEANING, which is the same defect as the `none`/`—` collision this section was
   written to fix, arriving from the other direction. The mark now comes from the
   markup; CSS supplies one only for a genuinely empty cell. */
.rs-absent:empty::after{content:"⊘"}   /* ⊘ LITERAL, deliberately.
   ⛔ THIS LINE LANDED IN f272ba5, WHICH IS A MIXED COMMIT. Reverting that
   commit whole to back this out would SILENTLY DROP 17 REASONED data-why CELLS
   from web/femtocell-matrix.html (13 of its 22 added lines are lucid-console154's,
   1 is this fix). REVERT THIS LINE, NEVER THE COMMIT.
   [A commit message cannot be annotated, so the warning lives at the point of
    use — where someone backing this out will actually be standing.]
   ⏳ EXPIRY, and it is TESTABLE rather than a date: this warning is spent once
   this line has been CHANGED by any commit after f272ba5, because a revert of
   f272ba5 will then CONFLICT rather than apply silently — and a conflict is its
   own warning. Check with:
       git log --oneline f272ba5.. -S'rs-absent:empty::after' -- web/realm-tokens.css
   Non-empty ⇒ DELETE THIS BLOCK. (Added 2026-09-12 at lucid-console154's ask:
   a hazard comment with no expiry becomes permanent furniture that a later
   reader cannot evaluate.)
   A CSS numeric escape here (backslash, then the four hex digits for this
   glyph) is RE-PARSED AS AN OCTAL ESCAPE when this block is embedded in a
   non-raw Python string: render-runbooks.py turned it into a 0x12 control
   character in the rendered page. The sync guard caught it.
   ⭐ AND THE FIRST VERSION OF THIS COMMENT REPRODUCED THE BUG — it spelled
   the escape out in prose, and the prose was mangled identically. The
   sequence is dangerous ANYWHERE in the block, including in text about it.
   ⇒ So: literal glyphs only here, and never write the escape form down. */          /* ⊘, fallback only */

/* --- THE CATEGORY IS A MACHINE KEY; THE REASON IS REAL TEXT -----------------
   `data-why` carries a value from the CLOSED SET below. The human sentence stays
   in the markup as a real span.
   ⛔ NEVER content: attr(data-why) -- generated content is not reliably
      selectable, not reliably read aloud, and does not survive copy/paste. The
      attribute is for MACHINES; the span is for PEOPLE. Neither restates the
      other, so neither can rot against the other.
   ⭐ THE SET IS CLOSED SO IT CAN BE ASSERTED. A value outside it is a defect,
      and that assertion is what would have caught `n/a` drifting in beside `⊘`:
      two names for one meaning is exactly a category that was never enumerable.
        no-unit         no live device -- documentary only
        not-checked     never asked of this unit
        not-read        exists and was not read
        not-derivable   depends on something unread
        not-measurable  blocked until a precondition clears
        not-applicable  does not exist for this device   <- absorbs the old `n/a`
   ⇒ Assert with:  grep -o 'data-why="[a-z-]*"' <surface> | sort -u
      and require the result to be a subset of the six above.
   📌 Derived from USAGE by lucid-console154 (6 no-unit, 6 not-checked, 1 not-read,
      1 not-derivable, 2 bare, 2 n/a), not invented. `not-applicable` is the one
      added deliberately: having it NAMED makes using it visibly a CLAIM, where
      `n/a` reads as a formatting choice. */

/* STRUCTURAL absences -- nothing is wrong and nothing is missing, so they get the
   lowest emphasis on the page. */
.rs-absent[data-why="no-unit"],
.rs-absent[data-why="not-applicable"]{opacity:.55}

/* GAPS -- we did not look, or could not. Deliberately NOT the same weight: a
   dotted rule says "something belongs here and is not here". Distinguishable
   WITHOUT COLOUR, so it survives greyscale, a screenshot and a colour-blind
   reader. */
.rs-absent[data-why="not-checked"],
.rs-absent[data-why="not-read"],
.rs-absent[data-why="not-derivable"],
.rs-absent[data-why="not-measurable"]{opacity:1;border-bottom:1px dotted currentColor}

/* 🔴 THE OMISSION DETECTOR, AND IT IS THE POINT OF THE WHOLE DESIGN.
   A cell with no `data-why` is a DEFECT, and it renders loudly so the omission is
   visible IN THE PAGE rather than only to someone who thinks to grep. Free prose
   with no category is how two cells ended up with no parseable reason at all. */
.rs-absent:not([data-why]){opacity:1;border-bottom:2px dashed var(--warn,currentColor)}
/* realm-tokens:end */"""


# The status vocabulary, substituted into all three pages the same way
# TOKENS_CSS is. Separate constant, separate marker: two blocks that sync
# independently must not share one region.
STATUS_CSS = r"""/* realm-status:begin */
/* --- the mark -------------------------------------------------------------
   FILLED = measured. HOLLOW = not established. The difference is deliberately
   structural rather than chromatic, so it survives greyscale, colour-blindness
   and a screenshot pasted into a chat thread. Colour is never the only
   carrier: every mark is paired with a WORD by the surface using it. */
.rs-mark{width:8px;height:8px;border-radius:50%;display:inline-block;flex:none}
.rs-mark.ok{background:var(--ok)}
.rs-mark.warn{background:var(--warn)}
.rs-mark.bad{background:var(--bad)}
/* stale = READ, correctly, at a time that is no longer now. Filled, because
   something WAS measured -- the doubt is about its age, not its existence. */
.rs-mark.stale{background:var(--stale)}
/* unknown = NOT MEASURED. Hollow, slightly larger so the ring is legible at
   small sizes, and never a default green. */
.rs-mark.unknown{background:none;border:2px solid var(--idle);width:9px;height:9px}

/* --- the chip -------------------------------------------------------------
   A state and its word travelling together. The word is not optional. */
.rs-chip{display:inline-flex;align-items:center;gap:var(--s1,4px);
  font-family:var(--mono);font-size:var(--t-xs,11px);letter-spacing:.06em;
  text-transform:uppercase;padding:3px var(--s2,8px);border-radius:999px;
  border:1px solid var(--line);color:var(--ink2);white-space:nowrap}
.rs-chip.ok{color:var(--ok);border-color:currentColor}
.rs-chip.warn{color:var(--warn);border-color:currentColor}
.rs-chip.bad{color:var(--bad);border-color:currentColor}
.rs-chip.stale{color:var(--stale);border-color:currentColor;
  background:var(--stale-bg)}
.rs-chip.unknown{color:var(--idle);border-color:currentColor}

/* --- provenance -----------------------------------------------------------
   RIDES ON THE VALUE, NEVER ON THE PANEL. A panel-level "live" badge becomes a
   lie the moment one value inside that panel is cached, and that is not a
   hypothetical: it is how "inferred" came to cover both "derived from
   something else" and "nothing was read at all" on :8080.
   Vocabulary: live · cached · polled Ns · window T · inferred · not checked.
   "total" is deliberately NOT here -- it describes the number, not where the
   number came from, and belongs in the label. */
.rs-prov{font-family:var(--mono);font-size:var(--t-xs,11px);color:var(--ink2);
  margin-left:var(--s1,4px);white-space:nowrap}
.rs-prov::before{content:"\00b7\00a0"}
/* The one provenance that is NOT a dimmed footnote. "not checked" is the
   absence of a measurement and must not read as a quiet qualifier on a real
   one -- it is the whole verdict. */
.rs-prov.unknown{color:var(--idle);font-style:italic}
.rs-prov.stale{color:var(--stale)}

/* ⇒ THE ABSENCE VOCABULARY MOVED TO `realm-tokens` (2026-09-12).
   It is a PRIMITIVE, not panel furniture: it depends only on --idle and --warn,
   and two surfaces that do NOT carry this block were already rendering 224 em
   dashes between them with no way to say which KIND of absence they meant
   (exchange-status 170, femtocell-matrix 54).
   ⭐ AN OPTIONAL BLOCK A SURFACE MUST REMEMBER TO ADOPT IS THE SAME FAILURE
   SHAPE AS AN EXCLUSION NOBODY RE-CHECKS. A universal concept belongs in the
   universal block, where nobody has to remember.
   ⚠️ The header removed with it said "absence has THREE meanings" while the
   rules beneath it defined SIX — a stale heading over correct rules, shipped by
   me in d6840af. What stays here is genuinely panel furniture: .rs-chip,
   .rs-mark, .rs-prov. */

@media (prefers-reduced-motion:no-preference){
  .rs-chip{transition:color .15s,border-color .15s}
}
/* realm-status:end */"""


# ---------------------------------------------------------------------------
# Identity / realm-sigil
#
# CLAUDE.md requires every HTTP surface to carry a realm-sigil /api/version and
# be registered in status.realm.watch/checks.json. This mirrors the contract in
# web/exchange-status.py field-for-field -- same vendored word lists, same
# generate_name port -- so one hash yields ONE name across every implementation.
# Vendored rather than imported to keep this file stdlib-only and self-contained.
#
# ⚠️ ONE SIGIL ENDPOINT, NOT TWO. `/inventory` is a second PAGE, not a second
# service: it runs in this process, off this build, and dies when this dies. A
# second /api/version would report identical data and monitor the same failure,
# so the status page would show two reds for one outage and overstate the
# breakage. The ledger's DISTINCT failure -- inventory.json unreadable while the
# service is fine -- is caught by a plain reachability check on /inventory in
# checks.json instead.
# ---------------------------------------------------------------------------

APP_NAME  = "console.gsm.realm.watch"
APP_DESC  = "Realm Telecom telephony console — routing, directory, call log"
APP_REALM = "signal"
APP_REPO  = "https://github.com/example/telephony-console"
BUILD_FILE = "/etc/telephony-console/build.json"

# Vendored from realm-sigil words/realms.json ("signal" realm).
SIGIL_ADJECTIVES = [
    "Amplified", "Beaconing", "Blinking", "Broadcast", "Broadcasting",
    "Channeled", "Channelled", "Decoded", "Echoing", "Encrypted", "Filtered",
    "Grounded", "Harmonic", "Humming", "Isolated", "Jittered", "Keyed",
    "Latched", "Looping", "Modulated", "Narrowed", "Oscillating", "Pulsed",
    "Pulsing", "Quantized", "Relayed", "Resonant", "Synced", "Syncing", "Tuned",
]
SIGIL_NOUNS = [
    "Antenna", "Beacon", "Broadcast", "Carrier", "Channel", "Diode", "Emitter",
    "Frequency", "Gate", "Harbor", "Harmonic", "Impulse", "Junction",
    "Keystone", "Lattice", "Lighthouse", "Link", "Modem", "Node", "Oscillator",
    "Packet", "Ping", "Pulsar", "Pulse", "Qubit", "Relay", "Semaphore",
    "Signal", "Telegraph", "Transponder",
]

_START_MONO = time.monotonic()
_START_ISO = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_name(hash_: str, realm: str = "signal") -> str:
    """Port of realm_sigil.generate_name — must agree with every other impl."""
    try:
        seed = int(hash_, 16) if hash_ != "dev" else 0
    except ValueError:
        seed = 0
    adj = SIGIL_ADJECTIVES[seed % len(SIGIL_ADJECTIVES)]
    noun = SIGIL_NOUNS[(seed >> 8) % len(SIGIL_NOUNS)]
    return f"{adj} {noun} · {hash_}"


def _build_info() -> dict:
    """Build metadata, injected at deploy time by scripts/deploy-console.sh.

    Python has no compile step, so there is no ldflags equivalent to
    realm-sigil's Go path. Falls back to reading git from the working directory
    (useful straight out of the repo), then to "dev"."""
    info = {"hash": "dev", "branch": "unknown", "dirty": False, "built": "unknown"}
    try:
        with open(BUILD_FILE) as fh:
            info.update(json.load(fh))
        return info
    except (OSError, ValueError):
        pass
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        run = lambda *a: subprocess.run(a, capture_output=True, text=True,
                                        cwd=here, timeout=5).stdout.strip()
        info["hash"] = run("git", "rev-parse", "--short", "HEAD") or "dev"
        info["branch"] = run("git", "rev-parse", "--abbrev-ref", "HEAD") or "unknown"
        info["dirty"] = subprocess.run(["git", "diff", "--quiet"], cwd=here,
                                       capture_output=True, timeout=5).returncode != 0
        info["built"] = _START_ISO
    except (OSError, subprocess.SubprocessError):
        pass
    return info


BUILD = _build_info()


def version_dict() -> dict:
    """The realm-sigil /api/version contract, field-for-field with :8080."""
    h = BUILD["hash"]
    return {
        "name": APP_NAME,
        "description": APP_DESC,
        "version": generate_name(h, APP_REALM),
        "hash": h,
        "branch": BUILD["branch"],
        "dirty": BUILD["dirty"],
        "built": BUILD["built"],
        "realm": APP_REALM,
        "repo": APP_REPO,
        "commit_url": f"{APP_REPO}/commit/{h}" if APP_REPO and h != "dev" else "",
        "started": _START_ISO,
        "uptime": int(time.monotonic() - _START_MONO),
        "runtime": "python%d.%d.%d" % sys.version_info[:3],
        "os": f"{sys.platform}/{platform.machine()}",
        "host": socket.gethostname(),
        "pid": os.getpid(),
    }


CONF     = "/etc/asterisk/extensions.conf"
MONITOR  = "/var/spool/asterisk/monitor"
# ⋯ [baseline elision: source lines 476–508 — voicemail, SMS, core-network and Home Assistant constants] ⋯
# ── VoIP.ms, ported 2026-09-13 ───────────────────────────────────────────────
VOIPMS_API = "https://voip.ms/api/v1/rest.php"
VOIPMS_UA = "2g-telephony-console/1.0"
# ⛔ THE CREDENTIAL FILE. NOT read into a dict -- see _voipms_creds(), which pulls
#    exactly three keys and discards every other line without ever holding it.
#    mode 640 root:asterisk: readable by the owner and by the asterisk group, so
#    it is reachable under either uid this service has run as. NOTHING MOVES --
#    no secret is copied, relocated or committed by this port.
VOIPMS_ENV = "/etc/asterisk/sms-gateway.env"
VOIPMS_SUBACCOUNT = "000000_house"
VOIPMS_INTERVALS = {"balance": 300, "registration": 300, "did": 3600}
VOIPMS_LOW_BALANCE = 5.00
VOIPMS_STALE_AFTER = 900
VOIPMS_STATE_DIR = os.environ.get("STATE_DIRECTORY", "/var/lib/telephony-console")
VOIPMS_CACHE_FILE = os.path.join(VOIPMS_STATE_DIR, "voipms.json")
# ⭐ SEED-ONLY, READ-ONLY. exchange-status's cache. On first start this console
#   has no cache of its own, and a blank balance for up to 300 s at the exact
#   moment of the bind would look like the merge broke the panel. We READ the
#   old file once if ours is absent and NEVER write to it -- two pollers writing
#   one file while both services are alive would be two writers, one truth.
VOIPMS_LEGACY_CACHE = "/var/lib/exchange-status/voipms.json"

# ⋯ [baseline elision: source lines 531–536 — Home Assistant contract constants and the SMS log parser] ⋯
CDR      = "/var/log/asterisk/cdr-csv/Master.csv"
PORT     = int(os.environ.get("TELEPHONY_CONSOLE_PORT", "8092"))

# ⛔ NOT 0.0.0.0. This page plays back the owner's call recordings and rewrites a live
# dialplan, and `pbx` carries FIVE interfaces -- including tun4/tun46, the
# GGSN's SUBSCRIBER DATA NETWORKS. Binding 0.0.0.0 opens the socket on those by
# construction, leaving only routing policy between a handset on packet data and
# the control surface. Binding the LAN address removes the socket from those
# interfaces entirely, so the protection does not depend on firewall or routing
# state staying as it is today.
#
# ⚠️ THE BIND IS A MITIGATION, NOT A FIX: the page is UNAUTHENTICATED, and the
# LAN it now listens on spans 14 VLANs. Anyone revisiting this should read it
# that way.
BIND     = os.environ.get("TELEPHONY_CONSOLE_BIND", "192.0.2.20")

# ⋯ [baseline elision: source lines 553–617 — cellular-core addresses, dialplan-writer regex, handset descriptions, test-extension catalogue] ⋯
# ---------------------------------------------------------------------------
# Readers. Each returns a dict that ALWAYS carries `src` (the command that
# produced it) and `ok` (whether the read succeeded). A failed read renders as
# "not probed", never as a default value.
# ---------------------------------------------------------------------------

# ⋯ [baseline elision: source lines 624–700 — the cellular-core console client] ⋯
def ast(cmd, timeout=10):
    """Run an Asterisk CLI command. Returns None if it could not be run."""
    try:
        r = subprocess.run(["asterisk", "-rx", cmd],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


# ⋯ [baseline elision: source lines 711–1606 — cellular readers: neighbour lists, TMSI/IMSI attribution, presence, IMSI census, Home Assistant call shaping] ⋯
# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND THREADS — A REGISTRY THAT REFUSES, NOT A COMMENT THAT ASKS
# ─────────────────────────────────────────────────────────────────────────────
# ⛔ WHY THIS EXISTS, AND IT IS NOT BOOKKEEPING.
#    /radio's on-demand DMI read was ruled safe on ONE property: NOTHING TAKES
#    THE SINGLE-CLIENT DMI LOCK IN THE BACKGROUND, so the lock is only ever held
#    by a human who asked for it and is waiting.
#    ⚠️ The check used to justify that was "grep this file for Thread( -- zero".
#    THAT IS A PROXY, NOT THE PROPERTY. The VoIP.ms poller below is a thread for
#    an entirely unrelated reason, so the proxy now reads FALSE while the
#    property is STILL TRUE -- and the next reader either raises a false alarm
#    about the DMI lock or re-derives safety from a check that stopped tracking
#    what it was standing in for.
# ⭐⭐⭐ SO THE CHECK IS NOW "WHAT DOES THIS THREAD TOUCH", NOT "IS THERE A THREAD",
#    and it is EXECUTABLE: start_background() REFUSES to start a thread that is
#    not registered here, and refuses one whose entry declares touches_dmi.
#    A future poller that reaches for the access point fails at start, loudly,
#    instead of passing a grep.
# ⚠️ REQUEST THREADS ARE NOT IN SCOPE AND THAT IS DELIBERATE. ThreadingHTTPServer
#    spawns one per request, and a request thread MAY take the DMI lock -- that
#    is exactly the on-demand path a human drives. The rule is about UNATTENDED
#    work. Registered threads are the ones nobody is waiting on.
BACKGROUND_THREADS = {
    # ⭐ THE SECOND LISTENER, for serving the old URL and the new one from ONE
    #   process during the consolidation. It is registered like everything else
    #   because start_background() REFUSES an unregistered thread -- the rule
    #   applies to my own code first.
    # ⚠️ WHAT IT TOUCHES IS *HTTP*, NOT A CELL. A request arriving on this
    #   listener may take the DMI lock exactly as one on the primary port may --
    #   that is the ATTENDED path, a human pressing Re-read and waiting. The
    #   listener itself polls nothing.
    "listener": {
        "touches": "an additional HTTP port, same handler as the primary",
        "touches_dmi": False,
        "touches_vty": False,
        "why_safe": "it serves requests; it originates none. Unattended work is "
                    "what this rule is about, and a listener does no work until "
                    "somebody asks",
    },
    "voipms": {
        "touches": "voip.ms HTTPS API (outbound, third-party) + a local JSON cache",
        "touches_dmi": False,
        "touches_vty": False,
        "why_safe": "no femtocell is contacted, so the single-client DMI console "
                    "is never held by this thread",
    },
}


def start_background(key, target):
    """Start a registered background thread, or refuse and say why.

    ⛔ THE REFUSAL IS THE POINT. An unregistered background thread cannot start,
      so "is there unattended work touching the AP console?" is answered by the
      program rather than by whoever last read the comments.
    """
    entry = BACKGROUND_THREADS.get(key)
    if entry is None:
        raise RuntimeError(
            "refusing to start background thread %r: it is not in "
            "BACKGROUND_THREADS. Every unattended thread must declare what it "
            "touches -- see the block above start_background()." % key)
    if entry.get("touches_dmi") or entry.get("touches_vty"):
        raise RuntimeError(
            "refusing to start background thread %r: it declares "
            "touches_dmi=%r touches_vty=%r. Unattended work must not hold the "
            "single-client access-point console; that is the property /radio's "
            "on-demand read depends on."
            % (key, entry.get("touches_dmi"), entry.get("touches_vty")))
    t = threading.Thread(target=target, name="bg:" + key, daemon=True)
    t.start()
    return t


def background_thread_audit():
    """Live state of the rule above, for a gate to read rather than infer."""
    live = {t.name[3:] for t in threading.enumerate() if t.name.startswith("bg:")}
    unregistered = sorted(live - set(BACKGROUND_THREADS))
    return {
        "ok": not unregistered and not any(
            v.get("touches_dmi") or v.get("touches_vty")
            for v in BACKGROUND_THREADS.values()),
        "registered": {k: dict(v) for k, v in BACKGROUND_THREADS.items()},
        "running": sorted(live),
        # ⛔ Registered-but-not-running is NOT a failure of this rule -- a poller
        #   that has not been started yet, or has died, is a different problem
        #   and is reported separately rather than folded into a boolean.
        "registered_not_running": sorted(set(BACKGROUND_THREADS) - live),
        "unregistered_running": unregistered,
        "rule": "an unattended thread must declare what it touches, and must not "
                "touch the single-client DMI console",
    }


_CONSUMERS = {"since": None, "by": {}}
_CONSUMERS_LOCK = threading.Lock()
# ⛔ A CAP, SO A SCANNER CANNOT GROW THIS WITHOUT BOUND -- and when it is hit the
#   payload SAYS SO, because a truncated tally reads exactly like a complete one.
CONSUMERS_MAX = 400


def _consumer_note(peer, port, path):
    """Tally who asked for what, on which port. In memory; never logged."""
    with _CONSUMERS_LOCK:
        if _CONSUMERS["since"] is None:
            _CONSUMERS["since"] = time.time()
        b = _CONSUMERS["by"]
        k = "%s|%s|%s" % (peer, port, path)
        if k not in b and len(b) >= CONSUMERS_MAX:
            _CONSUMERS["capped"] = True
            return
        e = b.get(k)
        if e is None:
            b[k] = {"peer": peer, "port": port, "path": path,
                    "count": 1, "first": time.time(), "last": time.time()}
        else:
            e["count"] += 1
            e["last"] = time.time()


def consumers_state():
    """Who is using this console, per PORT -- the instrument the merge removed.

    ⚠️ IN MEMORY, SO THE WINDOW STARTS AT THE LAST RESTART, AND THE WINDOW IS
      PUBLISHED BESIDE EVERY COUNT. A count without its window is the trap this
      corpus keeps carding: "zero requests" means nothing until you know whether
      you were looking for a minute or a month, and a consumer with a long period
      reads zero in a short window ON A HEALTHY SYSTEM.
    ⭐ THIS IS WHAT RETIRES :8092: not a date, and not a guess -- a port with no
      peers other than this host, over a window long enough to mean something.
    """
    now = time.time()
    with _CONSUMERS_LOCK:
        rows = [dict(v) for v in _CONSUMERS["by"].values()]
        since = _CONSUMERS["since"]
        capped = bool(_CONSUMERS.get("capped"))
    for r in rows:
        r["first_ago_s"] = int(now - r.pop("first"))
        r["last_ago_s"] = int(now - r.pop("last"))
    rows.sort(key=lambda r: -r["count"])
    per_port = {}
    for r in rows:
        p = per_port.setdefault(str(r["port"]), {"requests": 0, "peers": set()})
        p["requests"] += r["count"]
        p["peers"].add(r["peer"])
    return {
        "ok": True,
        "window_s": int(now - since) if since else 0,
        "window_note": "since this process started; NOT a lifetime total",
        "capped": capped,
        "cap": CONSUMERS_MAX,
        "why_capped": ("the distinct peer/port/path tally hit its cap, so these "
                       "counts are a FLOOR" if capped else None),
        "per_port": {k: {"requests": v["requests"],
                         "peers": sorted(v["peers"]),
                         "peer_count": len(v["peers"])}
                     for k, v in per_port.items()},
        "rows": rows[:120],
        "src": "in-process request tally (the journal is deliberately silent: "
               "this page auto-refreshes and would bury the host's other units)",
    }


def _voipms_scrub(text, *secrets):
    """Remove credentials from anything that could become an error string.

    ⛔ CONDITION FROM THE PORT REVIEW: the env contents must never reach an error
      path. A root-or-service web server with a credential in scope is the shape
      where one unhandled traceback is a disclosure.
    ⭐ TWO MECHANISMS, BECAUSE EITHER ALONE HAS A HOLE:
        · replace the literal secret VALUE -- catches any path, including ones
          nobody anticipated, but misses a percent-encoded form;
        · rewrite `api_password=...` -- catches the encoded form in a URL, but
          only where the query shape survives.
      Neither is sufficient; together they cover the two ways it escapes.
    """
    out = str(text)
    for s in secrets:
        # ⛔ A DEGENERATE SECRET MAKES THE VALUE-REPLACEMENT DESTRUCTIVE, AND IT
        #   FAILS TOWARD LOOKING LIKE IT WORKED:
        #     s == ""  -> str.replace("", "***") INSERTS *** BETWEEN EVERY
        #                 CHARACTER. The "redacted" message is garbage and reads
        #                 as a corrupted log, not as a missing credential.
        #     s == "a" -> every letter 'a' in the message is redacted. The text
        #                 becomes unreadable AND a reader may conclude the
        #                 redactor is working while it is destroying evidence.
        #   ⇒ The length floor is not tuning: below it the mechanism is harmful.
        if s and len(s) >= 8:
            out = out.replace(s, "***")
            out = out.replace(urllib.parse.quote(s, safe=""), "***")
    # ⭐ ALWAYS, REGARDLESS OF THE ABOVE. This is the mechanism that must never be
    #   skipped -- it is the one that holds when the value-replacement is
    #   disqualified, and a short password is exactly when the belt is gone.
    out = re.sub(r"(api_password=)[^&\s\"']*", r"\1***", out)
    return out


def _voipms_creds():
    """Exactly three keys out of the credential file. Nothing else is retained.

    ⛔ THE WHOLE FILE IS NEVER HELD IN A VARIABLE. exchange-status builds a dict
      of every line and then indexes three of them; this reads line by line,
      keeps the three it needs and discards the rest, so nothing else in that
      file is ever in this process's memory to leak into a traceback, a repr or
      a debugger.
    """
    user = pw = did = None
    with open(VOIPMS_ENV, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            # ⛔ TOLERANCE, NOT AN ASSERTION ABOUT THE FILE. This parser used to be
            #   correct BECAUSE the file happens to carry no `export` and no
            #   quotes -- "right by luck", with nothing in the code or the tests
            #   depending on it deliberately. Both are completely ordinary edits
            #   to a .env, and either one fails in the worst direction:
            #     export VOIPMS_PASS=x  -> key is "export VOIPMS_PASS" -> NO MATCH
            #     VOIPMS_PASS="x y"     -> value keeps its quotes -> auth fails
            #   ⇒ BOTH SURFACE AS "VoIP.ms rejected our credentials", which sends
            #     the next person to VoIP.ms rather than to this file.
            #   ⭐ Tolerating them REMOVES the dependency; documenting it would
            #     only have described it.
            k = re.sub(r"^export\s+", "", k.strip())
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]      # exactly one matching surrounding pair
            if k == "VOIPMS_USER":
                user = v
            elif k == "VOIPMS_PASS":
                pw = v
            elif k == "VOIPMS_DID":
                did = v
            # every other line falls out of scope here, unread and unstored
    if not user or not pw:
        # ⛔ NAMES THE PATH AND THE MISSING KEY, NEVER A VALUE.
        raise KeyError("VOIPMS_USER and VOIPMS_PASS must both be set in %s"
                       % VOIPMS_ENV)
    return user, pw, (did or "")


class VoipMsPoller:
    """Polls VoIP.ms in the background; the request path only reads snapshots.

    Ported from exchange-status 2026-09-13. Every public method is non-blocking
    and never raises. Failures are recorded in the snapshot as `error` and the
    previous good values are kept, so a VoIP.ms outage degrades to "last known
    balance, marked stale" rather than to a blank panel or a slow page.

    ⚠️ 21 of /api/ha's 86 keys are voipms_*, and 192.0.2.108 polls that contract
      every 60 s and cannot tell anyone it broke. This is not an optional panel.
    """

    PERSIST = ("balance", "spent_today", "calls_today", "time_today",
               "spent_total", "calls_total",
               "spent_today_measured", "calls_today_measured",
               "time_today_measured", "spent_total_measured",
               "calls_total_measured",
               "registered", "register_server",
               "register_ip", "register_next", "register_agent",
               "did_description", "did_sms_enabled", "did_e911",
               "did_next_billing", "did_routing", "fetched")

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            "balance": None, "spent_today": None, "calls_today": None,
            "time_today": None, "spent_total": None, "calls_total": None,
            # ⭐ PROVENANCE SIBLINGS. The value keys stay ALWAYS-A-NUMBER once
            #   polled -- a contract consumers depend on -- and these say whether
            #   the number was REPORTED or is the `or 0` default.
            #   ⛔ None = UNKNOWN, deliberately, NOT False: a restored disk cache
            #   carries a REAL number with the flag absent, and a False default
            #   would render "not measured" against a valid reading. A wrong
            #   provenance label is worse than none.
            "spent_today_measured": None, "calls_today_measured": None,
            "time_today_measured": None, "spent_total_measured": None,
            "calls_total_measured": None,
            "registered": None, "register_server": None, "register_ip": None,
            "register_next": None, "register_agent": None,
            "did_description": None, "did_sms_enabled": None,
            "did_e911": None, "did_next_billing": None, "did_routing": None,
            "fetched": {},
            "error": None,
        }
        # ⛔ NOT IN _data, THEREFORE NOT PERSISTED. It used to live there, so
        #   _save() wrote started=true to disk and _load() restored it -- start()
        #   returned early and the thread never ran again. The balance still
        #   DISPLAYED from the disk cache while silently never updating, which is
        #   worse than showing nothing: a low-balance alert that cannot fire
        #   looks exactly like one with nothing to report.
        self._started = False
        self._load()

    def _load(self):
        for path, is_legacy in ((VOIPMS_CACHE_FILE, False),
                                (VOIPMS_LEGACY_CACHE, True)):
            try:
                with open(path, encoding="utf-8") as fh:
                    disk = json.load(fh)
            except (OSError, ValueError):
                continue
            if isinstance(disk, dict):
                self._data.update({k: v for k, v in disk.items()
                                   if k in self.PERSIST})
                # ⭐ SEED ONCE, FROM THE RETIRING SERVICE, READ-ONLY. Stop at the
                #   first file that loads: our own wins if it exists.
                # ⛔ THE SEED CARRIES THE SOURCE'S OWN `fetched` TIMESTAMPS, NOT
                #   THE TIME OF THE SEED -- `fetched` is in PERSIST and is copied
                #   verbatim. If seeding stamped "now", a cache exchange-status
                #   last wrote two days ago would present as FRESH, and
                #   voipms_age -- a key this contract ships -- becomes a lie at
                #   exactly the moment several lanes are watching the bind for
                #   regressions.
                #   ⭐ An honestly stale number is fine; a falsely fresh one is
                #     the failure this corpus keeps carding.
                return

    def _save(self):
        try:
            os.makedirs(VOIPMS_STATE_DIR, exist_ok=True)
            tmp = VOIPMS_CACHE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({k: self._data[k] for k in self.PERSIST}, fh)
            os.replace(tmp, VOIPMS_CACHE_FILE)   # atomic; never a torn file
        except OSError:
            pass   # a cache we cannot persist is still a cache

    def _call(self, method, user, pw, **params):
        q = urllib.parse.urlencode({"api_username": user, "api_password": pw,
                                    "method": method, **params})
        req = urllib.request.Request(VOIPMS_API + "?" + q,
                                     headers={"User-Agent": VOIPMS_UA})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            hint = (" — a bare 403 here is usually the WAF rejecting the "
                    "User-Agent, not the credentials or the IP whitelist"
                    if e.code == 403 else "")
            raise RuntimeError("%s: HTTP %s%s" % (method, e.code, hint)) from None
        except Exception as e:
            # ⛔ SCRUBBED, AND `from None`: the chained original carries the
            #   Request object, and a traceback that reaches a log or an HTTP
            #   error body would carry the query string with it.
            raise RuntimeError(_voipms_scrub("%s: %s" % (method, e), pw)) from None
        if body.get("status") != "success":
            raise RuntimeError("%s: %s" % (method, body.get("status")))
        return body

    def _refresh_once(self):
        now = time.time()
        try:
            user, pw, did = _voipms_creds()
        except (OSError, KeyError) as e:
            with self._lock:
                # names the PATH and the missing KEY; no value can appear here
                self._data["error"] = "credentials unreadable (%s): %s" % (
                    VOIPMS_ENV, e)
            return

        errs = []
        with self._lock:
            fetched = dict(self._data["fetched"])
        due = [s for s, iv in VOIPMS_INTERVALS.items()
               if now - fetched.get(s, 0) >= iv]

        for section in due:
            try:
                if section == "balance":
                    b = self._call("getBalance", user, pw, advanced="true")["balance"]
                    # ⛔ `or 0` DESTROYS A DISTINCTION THE RENDERER CANNOT RECOVER:
                    #   "VoIP.ms did not report this" and "it is zero" become the
                    #   same number one layer before anything can label it. Fixed
                    #   ADDITIVELY -- the value keys keep their always-a-number
                    #   contract and a _measured sibling carries the provenance.
                    # ⭐ THE TEST IS ON THE VALUE, NOT THE KEY. `"x" in b` would be
                    #   blind to a present-but-EMPTY field, and a flag reporting
                    #   "measured" for an empty value reinstates the exact
                    #   conflation it was added to remove. The `or 0` idiom is
                    #   itself the evidence that present-but-empty is the real
                    #   case: a bare .get() would already have handled an ABSENT
                    #   key by returning None, which float() rejects loudly.
                    def _m(key):
                        raw = b.get(key)
                        return raw, (raw not in (None, ""))
                    _st, _st_m = _m("spent_today")
                    _ct, _ct_m = _m("calls_today")
                    _tt, _tt_m = _m("time_today")
                    _sT, _sT_m = _m("spent_total")
                    _cT, _cT_m = _m("calls_total")
                    upd = {
                        "balance": float(b["current_balance"]),
                        "spent_today": float(_st or 0),
                        "calls_today": int(_ct or 0),
                        "time_today": _tt,
                        "spent_total": float(_sT or 0),
                        "calls_total": int(_cT or 0),
                        "spent_today_measured": _st_m,
                        "calls_today_measured": _ct_m,
                        "time_today_measured": _tt_m,
                        "spent_total_measured": _sT_m,
                        "calls_total_measured": _cT_m,
                    }
                elif section == "registration":
                    r = self._call("getRegistrationStatus", user, pw,
                                   account=VOIPMS_SUBACCOUNT)
                    regs = r.get("registrations") or []
                    first = regs[0] if regs else {}
                    upd = {
                        "registered": r.get("registered") == "yes",
                        "register_server": first.get("server_hostname"),
                        "register_ip": first.get("register_ip"),
                        "register_next": first.get("register_next"),
                        "register_agent": first.get("register_useragent"),
                    }
                else:   # did
                    ds = self._call("getDIDsInfo", user, pw, did=did)["dids"]
                    d = ds[0] if ds else {}
                    upd = {
                        "did_description": d.get("description"),
                        "did_sms_enabled": d.get("sms_enabled") == "1",
                        "did_e911": d.get("e911") == "1",
                        "did_next_billing": d.get("next_billing"),
                        "did_routing": d.get("routing"),
                    }
            except Exception as e:      # a poller must not die
                errs.append(_voipms_scrub(e, pw))
                continue
            with self._lock:
                self._data.update(upd)
                self._data["fetched"][section] = time.time()

        with self._lock:
            self._data["error"] = "; ".join(errs) if errs else None
            self._save()

    def _loop(self):
        # A short first delay lets the HTTP server bind and answer immediately;
        # the page is useful without VoIP.ms data and must not wait for it.
        time.sleep(2)
        while True:
            try:
                self._refresh_once()
            except Exception:           # never let the thread die
                pass
            time.sleep(30)              # cheap tick; _refresh_once honours the
                                        # per-section intervals itself

    def start(self):
        with self._lock:
            if self._started:
                return
            self._started = True
        # ⛔ THROUGH THE REGISTRY, NEVER threading.Thread DIRECTLY. See
        #   start_background(): an unregistered background thread cannot start.
        start_background("voipms", self._loop)

    def snapshot(self):
        """Instant, non-blocking. Never raises."""
        with self._lock:
            d = dict(self._data)
            fetched = dict(d.pop("fetched", {}))
            d["polling"] = self._started
        newest = max(fetched.values()) if fetched else 0
        age = int(time.time() - newest) if newest else None
        bal = d.get("balance")
        d["age"] = age
        d["stale"] = (age is None) or (age > VOIPMS_STALE_AFTER)
        d["fetched_at"] = (datetime.fromtimestamp(newest)
                           .strftime("%Y-%m-%d %H:%M:%S") if newest else None)
        d["balance_low"] = (bal is not None and bal < VOIPMS_LOW_BALANCE)
        d["low_threshold"] = VOIPMS_LOW_BALANCE
        # Months of line rental left, as the useful reading of a raw dollar
        # figure. Call minutes are extra but at ~1c/min they are noise next to
        # the monthly DID fee for a house line.
        d["months_left"] = round(bal / 2.35, 1) if bal is not None else None
        d["days_to_billing"] = None
        if d.get("did_next_billing"):
            try:
                nb = datetime.strptime(d["did_next_billing"], "%Y-%m-%d")
                d["days_to_billing"] = (nb - datetime.now()).days
            except ValueError:
                pass
        return d


VOIPMS = VoipMsPoller()

# ⋯ [baseline elision: source lines 2097–3411 — Home Assistant contract, cell and ACS state, status collectors, network dependencies, SMS, voicemail, femtocell readers] ⋯
def read_trunk():
    src = "asterisk -rx 'pjsip show registrations'"
    txt = ast("pjsip show registrations")
    if txt is None:
        return {"ok": False, "src": src, "why": "asterisk CLI not reachable"}
    for line in txt.splitlines():
        m = re.match(r'\s*(\S+)/(\S+)\s+(\S+)\s+(Registered|Unregistered|Rejected)'
                     r'\s*(\(exp\. (\d+)s\))?', line)
        if m:
            return {"ok": True, "src": src, "name": m.group(1), "uri": m.group(2),
                    "status": m.group(4), "expires": m.group(6), "raw": txt.strip()}
    return {"ok": True, "src": src, "status": None, "raw": txt.strip(),
            "why": "no registration row in output"}


def read_calls():
    """Active calls, from TWO independent instruments.

    Asterisk knows about channels; the MSC knows about subscriber connections.
    Reporting both means a disagreement is visible instead of averaged away, and
    a zero is only reported as zero when the instrument demonstrably answered.
    """
    out = {"instruments": [], "subscribers": {}}
    txt = ast("core show channels")
    if txt is None:
        out["instruments"].append({"name": "Asterisk channels", "ok": False,
                                   "src": "asterisk -rx 'core show channels'",
                                   "why": "asterisk CLI not reachable"})
    else:
        m = re.search(r'(\d+) active calls?', txt)
        p = re.search(r'(\d+) calls? processed', txt)
        out["instruments"].append({
            "name": "Asterisk channels", "ok": True,
            "src": "asterisk -rx 'core show channels'",
            "value": int(m.group(1)) if m else None,
            "note": f"{p.group(1)} calls processed since start" if p else None,
            "raw": txt.strip()})
    try:
        # `show connection` is key-free. `show subscriber cache`, which would
        # also answer this, prints Ki/OPc and is prohibited.
        t = vty(MSC_VTY, "show connection")
        rows = [l for l in t.splitlines() if l.strip()]
        inst = {"name": "MSC connections", "ok": True,
                "src": "cell-core vty 4254: show connection",
                "raw": t.strip() or "(no output -- no connections)"}
        # Format observed live 2026-09-03 with a call up. One connection is a
        # `Connection #NN:` header plus ~6 indented detail lines -- so counting
        # LINES would have reported 7 calls for 1. Count the headers.
        #
        #   Connection #00:
        #       Subscriber: IMSI-...:MSISDN-1001:TMSI-0x...
        #       RAN connection state: MSC_A_ST_COMMUNICATING
        #       Use count: 1 (cc)
        #
        # A connection is NOT necessarily a call: `cc` is call-control, while a
        # location update or an SMS also opens one. The tag is the difference.
        # NB: the header line is INDENTED ("  Connection #00:"), so a bare
        # ^ anchor matches nothing and silently reports zero connections
        # while the reader is returning perfect data.
        blocks = re.split(r'^\s*Connection #\d+:', t, flags=re.M)[1:]
        subs = {}
        for b in blocks:
            msisdn = re.search(r'MSISDN-(\d+)', b)
            state = re.search(r'RAN connection state: (\S+)', b)
            tags = sorted(set(re.findall(r'Use count: \d+ \(([^)]*)\)', b)))
            if msisdn:
                subs[msisdn.group(1)] = {
                    "state": state.group(1) if state else None,
                    "tags": tags, "in_call": "cc" in tags}
        inst["value"] = len(blocks)
        if blocks:
            ncc = sum(1 for v in subs.values() if v["in_call"])
            inst["note"] = (f"{ncc} of {len(blocks)} carrying call-control; the "
                            f"rest are signalling only (location update, SMS)")
        out["subscribers"] = subs
        out["instruments"].append(inst)
    except Exception as e:
        out["instruments"].append({"name": "MSC connections", "ok": False,
                                   "src": "cell-core vty 4254: show connection",
                                   "why": str(e)})
    # ⚠️ These are NOT two measurements of one quantity, and comparing them for
    # equality manufactures a disagreement out of a subset relationship:
    #   Asterisk counts EVERY call (SIP, PSTN, cellular).
    #   The MSC counts only CELLULAR subscriber connections.
    # A PSTN call to a softphone is correctly 1 and 0. So Asterisk carries the
    # headline, the MSC says how many of those involve a handset, and the only
    # thing worth flagging is the genuinely impossible case: more cellular
    # connections than there are calls.
    by = {i["name"]: i for i in out["instruments"]}
    a = by.get("Asterisk channels", {})
    mc = by.get("MSC connections", {})
    out["value"] = a.get("value") if a.get("ok") else None
    out["cellular"] = mc.get("value") if mc.get("ok") else None
    out["impossible"] = (out["value"] is not None and out["cellular"] is not None
                         and out["cellular"] > out["value"])
    return out


# ⋯ [baseline elision: source lines 3510–3624 — systemd service list and the HLR subscriber reader] ⋯
def read_sip_endpoints():
    """Softphone endpoints. These ARE real registrations, so a presence dot is
    legitimate HERE and only here."""
    src = "asterisk -rx 'pjsip show endpoints'"
    txt = ast("pjsip show endpoints")
    if txt is None:
        return {"ok": False, "src": src, "why": "asterisk CLI not reachable"}
    # ⚠️ The /CID suffix is OPTIONAL: `2006/2006` has one, `cell-bridge` and
    # `voipms` do not. A regex that REQUIRES it does not merely skip those two
    # lines -- it leaves `cur` pointing at the previous endpoint, so the trunk's
    # own Contact line gets attributed to extension 2006 and an unregistered
    # handset renders as REGISTERED with someone else's contact. Parse every
    # endpoint so attribution stays correct, then filter.
    rows, cur = [], None
    for line in txt.splitlines():
        m = re.match(r'\s*Endpoint:\s+(\S+?)(?:/\S*)?\s+(\S+(?: \S+)*?)\s+(\d+) of', line)
        if m:
            cur = {"ext": m.group(1), "state": m.group(2).strip(),
                   "channels": int(m.group(3)), "contact": None}
            rows.append(cur)
            continue
        m = re.match(r'\s*Contact:\s+\S+/(\S+)\s+\S+\s+(\S+)\s', line)
        if m and cur:
            cur["contact"] = {"uri": m.group(1), "status": m.group(2)}
    # Only numeric endpoints are handsets. `cell-bridge` is the MNCC bridge and
    # `voipms` is the trunk -- infrastructure, reported by their own tiles.
    return {"ok": True, "src": src,
            "rows": [r for r in rows if r["ext"].isdigit()],
            "infra": [r for r in rows if not r["ext"].isdigit()]}


# ⋯ [baseline elision: source lines 3656–3800 — dialplan reader/writer for inbound ring-group routing] ⋯
# ---------------------------------------------------------------------------
# CDR + recordings
# ---------------------------------------------------------------------------

CDR_COLS = ["accountcode", "src", "dst", "dcontext", "clid", "channel",
            "dstchannel", "lastapp", "lastdata", "start", "answer", "end",
            "duration", "billsec", "disposition", "amaflags", "uniqueid",
            "userfield"]

# Rendered documentation, served so the shared nav can reach it. They are static
# files in the repo; without serving them the nav could only point one way --
# a browser refuses http:// -> file:// links, so the doc pages could link to the
# live surfaces but never the reverse.
DOCS = {
    "/build-guide": ("build-guide.html", "Build guide"),
    "/runbooks":    ("runbooks.html",    "Runbooks"),
    "/sources":     ("sources.html",     "Sources"),
}
DOC_DIR = os.environ.get("TELEPHONY_DOC_DIR", "/usr/local/lib/telephony-console")

SAFE_WAV = re.compile(r'^[A-Za-z0-9._-]+\.wav$')


def recordings_index():
    """uniqueid -> [{leg, file, bytes}]. Empty (not an error) if unreadable."""
    idx = {}
    try:
        names = os.listdir(MONITOR)
    except Exception:
        return idx
    for n in names:
        m = re.match(r'^([a-z]+)-(\d+\.\d+)(?:-([A-Z]+))?\.wav$', n)
        if not m:
            continue
        try:
            size = os.path.getsize(os.path.join(MONITOR, n))
        except OSError:
            continue
        idx.setdefault(m.group(2), []).append(
            {"kind": m.group(1), "leg": m.group(3) or "MIXED",
             "file": n, "bytes": size})
    for v in idx.values():
        v.sort(key=lambda r: (r["leg"] != "MIXED", r["leg"]))
    return idx


def describe(row):
    """A plain-language 'what happened', derived only from CDR fields."""
    ctx, dst, app, data = row["dcontext"], row["dst"], row["lastapp"], row["lastdata"]
    who = {"from-pstn": "inbound from PSTN", "from-cellular": "from a handset",
           "from-internal": "from a softphone"}.get(ctx, ctx or "unknown origin")
    if dst.startswith("*"):
        return f"{who} → test extension {dst}"
    if app == "Dial" and "voipms" in (data or ""):
        return f"{who} → outbound to PSTN"
    if app == "Dial":
        rung = re.findall(r'PJSIP/(\d+)', data or "")
        if rung:
            return f"{who} → rang {', '.join(rung)}"
    if app in ("Echo", "Playback", "VoiceMailMain", "Voicemail"):
        return f"{who} → {app}"
    return f"{who} → {dst or '?'}"


def read_cdr(limit=60):
    src = CDR
    try:
        with open(CDR, newline="") as f:
            rows = list(csv.reader(f))
    except Exception as e:
        return {"ok": False, "src": src, "why": str(e)}
    idx = recordings_index()
    out = []
    for r in rows[-limit:]:
        if len(r) < len(CDR_COLS):
            continue
        d = dict(zip(CDR_COLS, r))
        d["what"] = describe(d)
        d["recordings"] = idx.get(d["uniqueid"], [])
        out.append(d)
    out.reverse()
    return {"ok": True, "src": src, "rows": out, "total": len(rows),
            "monitor_readable": bool(idx) or os.access(MONITOR, os.R_OK)}


# ⋯ [baseline elision: source lines 3886–3942 — directory (HLR joined to handset descriptions) and dialplan globals] ⋯
def snapshot():
    """One parallel gather. The VTY reads are on localhost and cheap; running
    them concurrently keeps a refresh well under a second."""
    with ThreadPoolExecutor(max_workers=7) as ex:
        f = {k: ex.submit(v) for k, v in {
            "femto": read_femtocell, "trunk": read_trunk, "calls": read_calls,
            "services": read_services, "hlr": read_hlr, "sip": read_sip_endpoints,
            "cdr": read_cdr}.items()}
        r = {k: v.result() for k, v in f.items()}
    cell, sipr, notes = build_directory(r["hlr"], r["sip"],
                                        r["calls"].get("subscribers"))
    # ⛔ PAGE-FACING BOUNDARY. /api/state backs the console UI, so the IMEI
    #   values read by read_hlr() are stripped here. build_directory() above
    #   reads only `msisdn` and is unaffected -- the strip happens AFTER it so
    #   the directory cannot start depending on a field this surface will not
    #   publish. See read_hlr() for the surface distinction.
    if r["hlr"].get("rows"):
        r["hlr"] = dict(r["hlr"], rows=_without_imei(r["hlr"]["rows"]))
    r["directory"] = {"cellular": cell, "sip": sipr, "notes": notes,
                      "globals": dialplan_globals()}
    r["dial"] = read_dial()
    r["overrides"] = read_overrides()
    r["as_of"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    r["host"] = socket.gethostname()
    return r


# ---------------------------------------------------------------------------
# The page. Tokens are copied verbatim from web/build-guide.html so this reads
# as a sibling of the guide and the runbooks rather than a different product.
# Serif (--body) is kept for prose; the instrument chrome is sans + mono, which
# is what a control surface wants.
# ---------------------------------------------------------------------------

# ⋯ [baseline elision: source lines 3977–8656 — SIM/handset inventory, TAC lookup, radio power and band control, the radio and inventory page templates] ⋯
PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Telephony Console</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%230e7c86'/%3E%3Cpath d='M9 11c0-1 1-2 2-2h2l2 4-2 2c1 2 2 3 4 4l2-2 4 2v2c0 1-1 2-2 2C14 23 9 18 9 11z' fill='%23fff'/%3E%3C/svg%3E">
<style>
__TOKENS__
__STATUS__
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:var(--serif);font-size:15px;line-height:1.55;
  padding:0 20px 72px;overflow-x:hidden}
.wrap{max-width:1080px;margin:0 auto}

/* ---- header ---------------------------------------------------------- */
header{padding:34px 0 22px;border-bottom:1px solid var(--line);margin-bottom:26px}
h1{font-size:1.62rem;margin:0 0 6px;letter-spacing:-.02em;font-weight:650}
.lede{font-family:var(--serif);color:var(--ink2);margin:0;max-width:64ch;
  font-size:1.02rem}
.hbar{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-top:16px;
  font-size:.82rem;color:var(--ink2)}
.hbar code{font-family:var(--mono);font-size:.8rem}
.spacer{flex:1 1 auto}
  background:var(--bg2);color:var(--ink2);border:1px solid var(--line);
  border-bottom-color:transparent;border-radius:var(--radius-sm) var(--radius-sm) 0 0}
  border-color:var(--line2);border-bottom-color:var(--panel);font-weight:600;
  box-shadow:inset 0 2px 0 var(--brass)}
.apnone{color:var(--warn);font-size:.9rem;margin:.5rem 0 0}
/* FRESHNESS lives in the shared realm-status block now (.rs-chip/.rs-mark).
   This page's bespoke .fresh was 12 lines of CSS that only it had, which is
   precisely the drift the block exists to stop -- the next surface needing a
   freshness chip would have written a thirteenth line slightly differently. */

/* ---- sections & cards ------------------------------------------------ */
section{margin-bottom:34px}
h2{font-size:.76rem;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink2);font-weight:650;margin:0 0 14px;
  padding-bottom:8px;border-bottom:1px solid var(--line-soft)}
.card{background:var(--bg2);border:1px solid var(--line);border-radius:10px;
  padding:18px 20px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}
.tile{background:var(--bg2);border:1px solid var(--line);border-radius:10px;
  padding:15px 17px;min-width:0}
.tile h3{margin:0 0 9px;font-size:.72rem;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink2);font-weight:650}
.big{font-size:1.5rem;font-weight:650;letter-spacing:-.02em;line-height:1.2;
  overflow-wrap:anywhere}
.kv{display:flex;justify-content:space-between;gap:12px;padding:3px 0;
  font-size:.83rem;border-top:1px solid var(--line-soft);margin-top:7px;
  padding-top:7px}
.kv:first-of-type{border-top:0;margin-top:9px}
.kv span:first-child{color:var(--ink2);flex:none}
.kv span:last-child{font-family:var(--mono);font-size:.79rem;text-align:right;
  overflow-wrap:anywhere}

/* ---- status vocabulary ----------------------------------------------
   Every state pairs a dot with a WORD. Colour is never the only carrier,
   so the page survives greyscale and colour-blindness -- and "not probed"
   is a first-class state with its own hollow mark, never a default green. */
.st{display:inline-flex;align-items:center;gap:7px;font-size:.85rem;
  font-weight:550;white-space:nowrap}
.st i{width:9px;height:9px;border-radius:50%;flex:none;background:currentColor}
.st-ok{color:var(--ok)}
.st-bad{color:var(--bad)}
.st-warn{color:var(--warn)}
.st-unread{color:var(--idle)}
.st-unread i{background:transparent;border:1.5px solid currentColor}
.st-na{color:var(--idle)}
.st-na i{background:transparent;border:1.5px dashed currentColor}

/* ---- provenance ------------------------------------------------------ */
details.prov{margin-top:11px;border-top:1px solid var(--line-soft);padding-top:8px}
details.prov summary{font-size:.74rem;color:var(--idle);cursor:pointer;
  list-style:none;user-select:none}
details.prov summary::-webkit-details-marker{display:none}
details.prov summary::before{content:"▸ ";color:var(--idle)}
details.prov[open] summary::before{content:"▾ "}
details.prov summary:hover{color:var(--brass)}
.src{font-family:var(--mono);font-size:.73rem;color:var(--ink2);
  background:var(--code-bg);border:1px solid var(--line-soft);border-radius:5px;
  padding:7px 9px;margin-top:7px;overflow-x:auto;white-space:pre;display:block}

/* ---- banners --------------------------------------------------------- */
.banner{border-left:3px solid var(--warn);background:var(--warn-bg);
  border-radius:0 8px 8px 0;padding:13px 16px;margin-bottom:16px;
  font-family:var(--serif);font-size:.95rem}
.banner.bad{border-left-color:var(--bad);background:var(--bad-bg)}
/* Only the banner's OWN heading is a block. Scoping this to `b` alone turns
   every inline <b> inside a banner into a block, which orphans the punctuation
   after it onto its own line. */
.banner > b:first-child{font-family:var(--serif);font-weight:650;
  font-size:.88rem;display:block;margin-bottom:4px;letter-spacing:.01em}
.banner b{font-weight:650}
.banner code{font-family:var(--mono);font-size:.84em;
  background:rgba(0,0,0,.06);padding:1px 5px;border-radius:4px}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .banner code
  {background:rgba(255,255,255,.09)}}

/* ---- ring picker ----------------------------------------------------- */
.pick{display:flex;align-items:flex-start;gap:13px;padding:11px 2px;
  border-bottom:1px solid var(--line-soft);cursor:pointer}
.pick:last-of-type{border-bottom:0}
.pick input{margin-top:3px;width:17px;height:17px;accent-color:var(--brass);flex:none}
.pick .meta{flex:1;min-width:0}
.pick .nm{font-weight:600}
.pick .ex{font-family:var(--mono);font-size:.79rem;color:var(--ink2);margin-left:8px}
.pick .note{font-family:var(--serif);color:var(--ink2);font-size:.9rem;margin-top:1px}
.bar{display:flex;align-items:center;gap:14px;margin-top:16px;flex-wrap:wrap}
button{background:var(--brass);color:var(--panel);border:0;border-radius:7px;
  padding:9px 18px;font-size:.9rem;font-weight:600;cursor:pointer;
  font-family:var(--serif)}
button.ghost{background:transparent;color:var(--ink2);
  border:1px solid var(--line);font-weight:550}
button:disabled{opacity:.45;cursor:not-allowed}
button:focus-visible,input:focus-visible,summary:focus-visible,a:focus-visible
  {outline:2px solid var(--brass);outline-offset:2px;border-radius:3px}
.msg{font-size:.87rem;font-weight:550}
.msg.good{color:var(--ok)} .msg.bad{color:var(--bad)}
code.line{display:block;font-family:var(--mono);font-size:.78rem;
  background:var(--code-bg);border:1px solid var(--line-soft);border-radius:6px;
  padding:10px 12px;white-space:pre;overflow-x:auto;margin-top:6px}
.lbl{font-size:.72rem;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink2);font-weight:650;margin-top:16px}

/* ---- tables ---------------------------------------------------------- */
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:9px;
  background:var(--bg2)}
table{border-collapse:collapse;width:100%;font-size:.85rem;min-width:640px}
th{text-align:left;font-size:.7rem;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink2);font-weight:650;padding:10px 13px;
  border-bottom:1px solid var(--line);white-space:nowrap;
  background:var(--bg2);position:sticky;top:0}
td{padding:9px 13px;border-bottom:1px solid var(--line-soft);vertical-align:top}
tr:last-child td{border-bottom:0}
td.mono,th.mono{font-family:var(--mono);font-size:.79rem}
td .sub{color:var(--ink2);font-family:var(--serif);font-size:.88rem;margin-top:1px}
.tag{display:inline-block;font-size:.68rem;letter-spacing:.05em;font-weight:650;
  text-transform:uppercase;padding:2px 7px;border-radius:4px;
  background:var(--brass-soft);color:var(--brass);white-space:nowrap}
.tag.q{background:var(--warn-bg);color:var(--warn)}
.tag.n{background:var(--code-bg);color:var(--ink2)}

/* ---- tests ----------------------------------------------------------- */
.tests{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(290px,1fr))}
.test{background:var(--bg2);border:1px solid var(--line);border-radius:9px;
  padding:14px 16px}
.test .code{font-family:var(--mono);font-size:1.05rem;font-weight:600;
  color:var(--brass)}
.test .ttl{font-weight:600;margin:3px 0 5px}
.test p{font-family:var(--serif);color:var(--ink2);margin:0;font-size:.92rem}
.rec{display:inline-block;margin-top:9px;font-size:.7rem;letter-spacing:.05em;
  text-transform:uppercase;font-weight:650;color:var(--brass)}

/* ---- calls ----------------------------------------------------------- */
audio{width:100%;max-width:340px;height:34px;margin-top:5px}
.legs{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
  padding:4px 0 8px}
.leg b{font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink2);font-weight:650}
details.calls summary{cursor:pointer;font-size:.78rem;color:var(--brass);
  font-weight:600;list-style:none}
details.calls summary::-webkit-details-marker{display:none}
details.calls summary::before{content:"▸ play "}
details.calls[open] summary::before{content:"▾ hide "}
.disp-ANSWERED{color:var(--ok)} .disp-NOANSWER,.disp-BUSY{color:var(--warn)}
.disp-FAILED,.disp-CONGESTION{color:var(--bad)}

/* ================= CELLS AND HANDSETS =================
   ⛔ THIS BLOCK MUST STAY IN `PAGE`. The markup it styles is in PAGE. Six classes
   for /radio once lived in PAGE while their markup was in RADIO_PAGE, so every
   one of them was INERT -- the overview table, the neighbour matrix and the
   three-position control had no styling for as long as they existed, and the owner
   reported it as a request for nicer buttons. A stylesheet and its markup in
   different constants is not a smell, it is a silent total failure.
   tools/css-class-check.py detects it; it is not a substitute for keeping them
   together. */
.pr-grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(232px,1fr))}
.pr-cell{border:1px solid var(--line);border-radius:7px;padding:11px 13px 12px;
  background:var(--card,transparent);display:flex;flex-direction:column;gap:2px}
.pr-cell[data-up="no"]{opacity:.72;border-style:dashed}
.pr-nm{display:flex;align-items:baseline;justify-content:space-between;gap:8px;
  font-family:var(--mono);font-size:12.5px;letter-spacing:.04em;color:var(--brass);
  text-transform:uppercase;margin-bottom:3px}
.pr-nm .pr-ip{color:var(--idle);text-transform:none;letter-spacing:0;font-size:11.5px}
/* the load figure: the one genuinely realtime per-AP number on the page */
.pr-load{display:flex;gap:14px;margin:7px 0 5px;font-family:var(--mono)}
.pr-load div{display:flex;flex-direction:column;line-height:1.15}
.pr-load b{font-size:1.45rem;font-weight:600;color:var(--ink)}
.pr-load u{text-decoration:none;font-size:10.5px;letter-spacing:.09em;
  text-transform:uppercase;color:var(--idle)}
/* ⚠️ A HOLLOW figure is "never registered -- not measured". A solid 0 is a
   measured zero. They must not look alike; that distinction is the whole point. */
.pr-load b.pr-un{color:var(--idle);font-weight:400}
.pr-id{font-family:var(--mono);font-size:11.5px;color:var(--ink2);margin-top:3px}
/* --- IMSI census. Own prefix, deliberately: `.prov` is already shared with
   the other status page and collides there (confirmed by computed style
   2026-09-13), so a new panel gets a namespace nobody else is using rather
   than a generic one that reads well. --- */
.cs-sum{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:10px 0 4px}
.cs-win{font-family:var(--mono);font-size:11px;color:var(--idle);margin-left:auto}
.cs-amb{font-family:var(--serif);font-size:.87rem;color:var(--ink2);
  margin:6px 0 9px;line-height:1.45}
/* ⛔ THE TABLE SCROLLS INSIDE ITS OWN BOX. Eight columns of IMSIs will not fit a
   phone, and a page that scrolls sideways as a whole loses its nav. */
.cs-wrap{overflow-x:auto;margin-top:6px;border:1px solid var(--line);border-radius:7px}
table.cs{border-collapse:collapse;width:100%;font-size:12.5px}
table.cs th{font-family:var(--mono);font-size:10.5px;letter-spacing:.05em;
  text-transform:uppercase;color:var(--brass);text-align:left;font-weight:500;
  padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
table.cs td{padding:6px 10px;border-top:1px solid var(--line);vertical-align:baseline}
table.cs tbody tr:first-child td{border-top:0}
table.cs td.cs-id{font-family:var(--mono);font-size:11.5px;white-space:nowrap}
table.cs td.cs-n{font-family:var(--mono);text-align:right;font-variant-numeric:tabular-nums}
.cs-un{color:var(--idle);font-weight:400}
.cs-note{font-family:var(--serif);font-size:.92rem;color:var(--ink2);
  margin-top:8px;line-height:1.5}
/* --- the section index -------------------------------------------------- */
/* ⛔ THIS RULE MUST COME FIRST AND IT IS NOT DECORATION. `display:flex` below
   OUTRANKS the user-agent's `[hidden]{display:none}`, so the nav would render
   even while the attribute says it is hidden -- and the only case that exercises
   that is a page with FEWER THAN FOUR SECTIONS, which this one will never be
   again. The bug would ship invisible and surface on some future page that
   reuses this stylesheet. */
.sidx[hidden]{display:none}
.sidx{position:sticky;top:0;z-index:20;display:flex;gap:2px;flex-wrap:nowrap;
  overflow-x:auto;scrollbar-width:thin;
  margin:14px 0 2px;padding:7px 0;
  background:var(--bg);border-bottom:1px solid var(--line)}
.sidx a{flex:0 0 auto;text-decoration:none;white-space:nowrap;
  font-family:var(--mono);font-size:11px;letter-spacing:.04em;
  text-transform:uppercase;color:var(--ink2);
  padding:4px 10px;border:1px solid transparent;border-radius:20px}
.sidx a:hover{color:var(--ink);border-color:var(--line)}
/* ⛔ aria-current, not a class, so the state is in the ACCESSIBILITY TREE and
   not only in the paint. A screen reader gets the same "you are here" a sighted
   reader gets from the brass. */
/* ⚠️ var(--panel), NOT var(--card). I wrote --card from habit; this page has no
   such property and an undefined custom property does not fall back -- it makes
   the declaration INVALID AT COMPUTED-VALUE TIME, which silently drops it. The
   chip would still have looked "fine" because the border and the brass carry
   most of the state; the fill would simply never have appeared, and nothing
   anywhere would have said so. Checked against the :root block rather than
   assumed. */
.sidx a[aria-current="true"]{color:var(--brass);border-color:var(--line);
  background:var(--panel)}
.sidx a:focus-visible{outline:2px solid var(--brass);outline-offset:2px}
@media (prefers-reduced-motion: no-preference){html{scroll-behavior:smooth}}
/* A sticky index must not hide the heading it just jumped to. */
section[id]{scroll-margin-top:52px}
/* --- per-cell state --- */
.cl-grid{display:grid;gap:10px;margin-top:10px}
.cl-card{border:1px solid var(--line);border-radius:8px;padding:11px 14px}
.cl-hd{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;
  border-bottom:1px solid var(--line);padding-bottom:7px;margin-bottom:7px}
.cl-hd b{font-size:14px}
.cl-hd .cl-a{font-family:var(--mono);font-size:12px;color:var(--ink2)}
.cl-hd .cl-m{font-family:var(--mono);font-size:10px;letter-spacing:.05em;
  text-transform:uppercase;color:var(--idle);border:1px solid var(--line);
  border-radius:20px;padding:1px 8px}
.cl-row{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;padding:4px 0}
.cl-row>u{flex:0 0 4.6em;text-decoration:none;font-family:var(--mono);font-size:10px;
  letter-spacing:.05em;text-transform:uppercase;color:var(--idle)}
.cl-v{font-family:var(--mono);font-size:12px;color:var(--ink2)}
.cl-why{width:100%;font-family:var(--serif);font-size:.86rem;color:var(--ink2);
  margin:2px 0 0 5.6em;line-height:1.45}
/* --- ACS --- */
.acs-arm{border:1px solid var(--line);border-radius:8px;padding:11px 14px;margin-top:10px}
.acs-magic{font-family:var(--mono);font-size:13px;padding:2px 8px;border-radius:4px;
  border:1px solid var(--line)}
.acs-magic.bad{color:var(--bad);border-color:var(--bad)}
.acs-magic.ok{color:var(--ok)}
.acs-magic.warn{color:var(--brass)}
/* --- PSTN account --- */
.vm-bal{font-family:var(--mono);font-size:30px;line-height:1.1}
.vm-bal.vm-low{color:var(--bad)}
.vm-sub{font-family:var(--serif);font-size:.9rem;color:var(--ink2);margin-top:4px}
/* --- silent dependencies --- */
.nd{display:grid;gap:8px;margin-top:10px}
.nd-row{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;
  border:1px solid var(--line);border-radius:7px;padding:9px 13px}
.nd-row b{font-family:var(--mono);font-size:12.5px;color:var(--ink);min-width:15em}
.nd-d{font-family:var(--mono);font-size:12px;color:var(--ink2)}
.nd-b{font-family:var(--serif);font-size:.87rem;color:var(--ink2);
  width:100%;margin-top:2px}
.nd-row.nd-bad{border-color:var(--bad)}
.nd-row.nd-bad .nd-b{color:var(--ink)}
/* --- voicemail --- */
.vm-boxes{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0 4px}
.vm-box{border:1px solid var(--line);border-radius:7px;padding:8px 13px;min-width:104px}
.vm-box b{display:block;font-family:var(--mono);font-size:19px;line-height:1.15}
.vm-box u{display:block;text-decoration:none;font-family:var(--mono);font-size:10px;
  letter-spacing:.05em;text-transform:uppercase;color:var(--idle);margin-top:2px}
.vm-box.vm-new b{color:var(--brass)}
.vm-msg{border-top:1px solid var(--line);padding:9px 0}
.vm-msg:first-of-type{border-top:0}
.vm-hd{display:flex;gap:9px;align-items:baseline;flex-wrap:wrap;
  font-family:var(--mono);font-size:12px;color:var(--ink2)}
.vm-hd b{color:var(--ink)}
.vm-tx{font-family:var(--serif);font-size:.95rem;color:var(--ink);
  margin-top:5px;line-height:1.5}
.pr-grp{border:1px solid var(--line);border-radius:7px;padding:12px 14px;margin-top:12px}
.pr-ghd{font-family:var(--mono);font-size:12px;letter-spacing:.05em;
  text-transform:uppercase;color:var(--brass);margin-bottom:2px}
.pr-amb{font-family:var(--serif);font-size:.87rem;color:var(--ink2);
  margin:4px 0 9px;line-height:1.45}
.pr-sub{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;
  padding:5px 0;border-top:1px solid var(--line);font-family:var(--mono);font-size:12.5px}
.pr-sub:first-of-type{border-top:0}
.pr-sub .pr-ms{font-weight:600;color:var(--ink);min-width:3.4em}
.pr-sub .pr-im{color:var(--idle);font-size:11px}
.pr-where{display:flex;gap:5px;flex-wrap:wrap;margin-left:auto}
.pr-chip{border:1px solid var(--line);border-radius:20px;padding:1px 9px;
  font-size:11px;color:var(--ink2);white-space:nowrap}
/* a chip that is one of SEVERAL candidates is drawn as a candidate, not a fact */
.pr-chip.pr-maybe{border-style:dashed;color:var(--idle)}
.pr-chip.pr-sure{border-color:var(--brass);color:var(--brass)}
/* "last seen via" -- a SECOND fact beside the placement chips, never a louder one.
   It is deliberately quieter than the chips: the chips say where the core can place
   the handset NOW, this says where it was last HEARD, and the second must not be
   read as the first. */
.pr-seen{flex-basis:100%;margin:2px 0 0;font-family:var(--mono);font-size:11px;
  color:var(--idle);display:flex;gap:6px;flex-wrap:wrap}
.pr-seen b{font-weight:600;color:var(--ink2)}
.pr-seen .pr-rel{color:var(--idle)}
/* a bounded absence: "not seen in the window", NOT "never" */
.pr-seen.pr-nowin{font-style:italic}
@media (max-width:640px){
  .pr-where{margin-left:0;width:100%}
  .pr-load b{font-size:1.25rem}
}
footer{border-top:1px solid var(--line);padding-top:16px;margin-top:34px;
  font-family:var(--serif);color:var(--idle);font-size:.88rem}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
@media (max-width:640px){
  body{padding:0 14px 56px} h1{font-size:1.35rem}
  .kv{flex-direction:column;gap:1px} .kv span:last-child{text-align:left}
}
</style></head><body><div class="wrap">
<script src="/auth.js"></script>
<script>window.__REALM_HERE__="console";</script>
<!-- ⋯ [baseline elision: source lines 8998–9091 — realm navigation bar and section index] ⋯ -->
<section><h2>Live state</h2><div class="grid" id="live"></div></section>

<section><h2>PSTN account</h2>
  <p class="lede" style="margin-top:-2px">The VoIP.ms balance and the DID behind the
  house number. <em>This is the one thing that silently runs out and takes the line
  with it</em> &mdash; it is funded by hand, and nothing else on this page can tell you
  it is low.</p>
  <div id="voipms"></div></section>
<!-- ⋯ [baseline elision: source lines 9100–9184 — cellular, voicemail, SMS, inbound-routing, directory and test-extension sections] ⋯ -->
<section><h2>Recent calls</h2><div id="cdr"></div></section>

<section><h2>Fax &mdash; send a PDF from this page</h2>
  <div id="fax"></div>
  <div class="card">
    <div class="lbl">Send</div>
    <form id="faxform" onsubmit="return false" style="display:grid;gap:8px;max-width:640px">
      <label>Fax number <input id="faxnum" type="tel" inputmode="numeric" placeholder="202 555 0142"
        style="width:14em" autocomplete="off"></label>
      <label>Label <input id="faxlabel" type="text" placeholder="FORM-1" style="width:14em" maxlength="40"></label>
      <label>PDF <input id="faxfile" type="file" accept="application/pdf"></label>
      <label><input id="faxconfirm" type="checkbox"> I mean it &mdash; this dials the number above and delivers the document.</label>
      <div class="bar">
        <button id="faxsend" type="button">Send fax</button>
        <span class="msg" id="faxmsg" role="status" aria-live="polite"></span>
      </div>
    </form>
    <details class="prov"><summary>How a fax leaves this house</summary>
      <div style="font-family:var(--serif);font-size:.92rem;color:var(--ink2);margin-top:8px">
        The PDF is rendered to a Group-4 TIFF and Asterisk dials the number on the
        <code>voipms-fax</code> trunk view with <code>SendFax(&hellip;,f)</code>: plain G.711 audio,
        because VoIP.ms never accepts the T.38 switch (measured 2026-09-27; without
        <code>f</code> the call aborts). A call marked ANSWERED is not a delivered fax &mdash;
        the outcome column comes from the fax counters. The Canon MX922 still works too:
        dial <b>8</b> + 1 + number from it. All of this is the <code>fax</code> CLI
        (<code>~/Projects/fax</code>); this panel only calls it.
      </div>
      <span class="src">/usr/local/bin/fax --local --json send &lt;pdf&gt; &lt;number&gt;</span>
    </details>
  </div>
  <div id="faxlog"></div>
</section>

<footer id="foot"></footer>
</div>
<script>
const TESTS = __TESTS__;
const LEGS = {MIXED:"Mixed (both directions)",UP:"Uplink — from the handset",
  DOWN:"Downlink — sent to the handset",FROMCALLER:"From the caller",
  TOCALLER:"To the caller",FROMPSTN:"From the PSTN caller",TOPSTN:"To the PSTN caller"};
const esc = s => String(s==null?"":s).replace(/[&<>"']/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const st = (k,t) => `<span class="st st-${k}"><i></i>${esc(t)}</span>`;
const prov = (label,cmd,raw) => !cmd ? "" :
  `<details class="prov"><summary>${esc(label||"how this was read")}</summary>`+
  `<span class="src">${esc(cmd)}</span>`+
  (raw?`<span class="src">${esc(raw)}</span>`:"")+`</details>`;
const kb = n => n<1024?n+" B":n<1048576?(n/1024).toFixed(0)+" KB":(n/1048576).toFixed(1)+" MB";

/* ⋯ [baseline elision: source lines 9234–9625 — cellular presence, IMSI census, cell-hardware and ACS renderers] ⋯ */
let VOIPMS_SEEN = false;
function renderVoipms(v){
  const el = document.getElementById("voipms");
  if(!el) return;
  if(!v){ return; }
  const bal = v.balance;
  /* ⛔ NEVER READ: the poller has not completed a fetch. NOT "$0.00".
     A balance of zero and a balance nobody has fetched are opposite facts and
     both render as a small number if you let them. */
  if(bal === null || bal === undefined){
    el.innerHTML = `<div class="card">${st("unread","balance not read yet")}
      <div class="cs-amb">${v.polling
        ? "The background poller is running; the first VoIP.ms fetch takes up to "
          + "five minutes. This is not zero &mdash; it is <b>not yet known</b>."
        : "<b>The poller is not running.</b> Nothing will refresh this."}
        ${v.error?"<br>Last error: "+esc(v.error):""}</div>
      ${prov("source","voip.ms API, background poll")}</div>`;
    return;
  }
  VOIPMS_SEEN = true;
  /* ⚠️ STALE IS A SEPARATE AXIS FROM LOW. A stale balance may be fine and may be
     catastrophic, and the page cannot tell which — so it reports both and lets
     neither hide the other. */
  const low = v.balance_low === true;
  const age = v.age===null||v.age===undefined ? "never"
            : (v.age<90 ? v.age+"s ago"
               : (v.age<5400 ? Math.round(v.age/60)+"m ago"
                             : Math.round(v.age/3600)+"h ago"));
  const months = (v.months_left===null||v.months_left===undefined)
               ? "" : `<div class="vm-sub">about <b>${v.months_left}</b> months of line
                       rental at the current DID fee &mdash; call minutes are extra and
                       are noise beside it.</div>`;
  const bill = (v.days_to_billing===null||v.days_to_billing===undefined)
             ? "" : `<div class="vm-sub">next billing in <b>${v.days_to_billing}</b>
                     days${v.did_next_billing?` (${esc(v.did_next_billing)})`:""}.</div>`;
  /* ⚠️ THREE-STATE, like SMS `bound`: null means the poller has not fetched the
     registration section, which is NOT "not registered". */
  const reg = v.registered === true ? st("ok","registered with VoIP.ms")
            : (v.registered === false ? st("bad","NOT registered with VoIP.ms")
               : st("idle","registration not fetched yet"));
  /* ⭐ TWO INDEPENDENT WITNESSES TO ONE FACT, and the page says when they differ.
     asterisk's own view is on the PSTN trunk tile; this is VoIP.ms's view of us.
     A self-consistent instrument cannot detect its own staleness. */
  const agree = v.registered === null || v.registered === undefined ? ""
    : (v.agrees_with_asterisk === false
        ? `<div class="cs-amb">&#9888; <b>VoIP.ms and asterisk disagree about this
           trunk.</b> One of the two is stale or the registration is flapping;
           neither view alone can tell you which.</div>` : "");
  el.innerHTML = `<div class="cs-sum">${reg}
      <span class="cs-win">balance read ${esc(age)}${v.stale?" &middot; STALE":""}</span></div>
    <div class="card">
      <div class="vm-bal${low?" vm-low":""}">$${bal.toFixed(2)}</div>
      <div class="vm-sub">VoIP.ms balance${low
        ? ` &mdash; <b>below the $${v.low_threshold.toFixed(2)} alert threshold</b>` : ""}.</div>
      ${months}${bill}
    </div>
    ${agree}
    ${v.did_description?`<div class="vm-sub">DID: ${esc(v.did_description)}${
       v.did_sms_enabled?" &middot; SMS enabled":""}${v.did_e911?" &middot; E911":""}</div>`:""}
    ${v.error?`<div class="cs-amb">Last poll error: ${esc(v.error)}</div>`:""}
    ${prov("source","voip.ms API, polled every 300s in the background")}`;
}
async function loadVoipms(){
  try{ renderVoipms(await (await fetch("/api/voipms")).json()); }
  catch(e){
    const el=document.getElementById("voipms");
    if(el && !VOIPMS_SEEN)
      el.innerHTML=`<div class="card">${st("unread","balance not read")}
        <div class="cs-amb">${esc(String(e&&e.message||e))}</div></div>`;
  }
}
let NETDEPS_SEEN = false;
/* ⋯ [baseline elision: source lines 9698–9911 — network-dependency, SMS, voicemail and census renderers; section index] ⋯ */
function tileTrunk(t){
  if(!t.ok) return `<div class="tile"><h3>PSTN trunk</h3>
    <div class="big">${st("unread","not probed")}</div>
    <div class="kv"><span>why</span><span>${esc(t.why)}</span></div>${prov("source",t.src)}</div>`;
  const reg = t.status==="Registered";
  return `<div class="tile"><h3>PSTN trunk</h3>
    <div class="big">${t.status?(reg?st("ok","registered"):st("bad",t.status)):st("warn","no registration row")}</div>
    ${t.name?`<div class="kv"><span>trunk</span><span>${esc(t.name)}</span></div>`:""}
    ${t.uri?`<div class="kv"><span>server</span><span>${esc(t.uri)}</span></div>`:""}
    ${t.expires?`<div class="kv"><span>renews in</span><span>${esc(t.expires)}s</span></div>`:""}
    ${prov("source",t.src,t.raw)}</div>`;
}
function tileCalls(c){
  const insts = c.instruments||[];
  const head = c.value===null ? st("unread","not probed")
    : c.impossible ? st("warn","more cellular connections than calls")
    : c.value===0 ? st("ok","no calls in progress")
    : st("ok", c.value+" in progress");
  return `<div class="tile"><h3>Active calls</h3><div class="big">${head}</div>
    ${insts.map(i=>`<div class="kv"><span>${esc(i.name)}</span><span>${
      i.ok? (i.value===null?"—":i.value) : "not probed"}</span></div>`).join("")}
    ${insts.filter(i=>i.note).map(i=>`<div style="font-family:var(--serif);
      font-size:.85rem;color:var(--ink2);margin-top:7px">${esc(i.note)}</div>`).join("")}
    <div style="font-family:var(--serif);font-size:.85rem;color:var(--ink2);margin-top:8px">
      Asterisk counts every call; the MSC counts only the cellular ones, so the
      second number is a <em>subset</em> of the first and is normally lower.
      ${c.impossible?"<b>Right now it is higher, which should not be possible.</b>":""}
    </div>
    ${insts.map(i=>prov(i.name,i.src,i.raw||i.why)).join("")}</div>`;
}
/* ⋯ [baseline elision: source lines 9942–10097 — services tile; override, ring-picker, directory and test-extension renderers] ⋯ */
/* --- CDR ------------------------------------------------------------ */
function renderCdr(c){
  const el=document.getElementById("cdr");
  if(!c.ok){ el.innerHTML=`<div class="banner bad"><b>The call log could not be
    read</b><code>${esc(c.src)}</code> — ${esc(c.why)}</div>`; return; }
  el.innerHTML = `<div class="scroll"><table><thead><tr>
    <th>Started</th><th>What happened</th><th>From</th><th>Result</th>
    <th class="mono">Talk</th><th>Recording</th></tr></thead><tbody>
    ${c.rows.map(r=>{
      const dc="disp-"+r.disposition.replace(/[^A-Z]/g,"");
      return `<tr>
      <td class="mono">${esc(r.start.slice(5,16))}</td>
      <td>${esc(r.what)}<div class="sub">${esc(r.lastapp)}${
        r.lastdata?" · "+esc(r.lastdata.slice(0,58)):""}</div></td>
      <td class="mono">${esc(r.src||"—")}</td>
      <td class="${dc}">${esc(r.disposition)}</td>
      <td class="mono">${r.billsec}s</td>
      <td>${r.recordings.length?`<details class="calls"><summary>${
          r.recordings.length} file${r.recordings.length>1?"s":""}</summary>
        <div class="legs">${r.recordings.map(g=>`<div class="leg">
          <b>${esc(LEGS[g.leg]||g.leg)}</b> <span style="color:var(--idle);
            font-size:.72rem">${kb(g.bytes)}</span>
          <audio controls preload="none" src="/audio/${encodeURIComponent(g.file)}"></audio>
        </div>`).join("")}</div></details>`
        : `<span style="color:var(--idle);font-size:.8rem">—</span>`}</td>
    </tr>`;}).join("")}</tbody></table></div>
    <p style="font-family:var(--serif);color:var(--ink2);font-size:.9rem;margin-top:10px">
    Newest first, last ${c.rows.length} of ${c.total} records.
    ${c.monitor_readable?"":"<b>Recordings are not readable by this service</b>, so the file column is empty even where a recording exists."}
    </p>`;
}

/* --- fax ------------------------------------------------------------ */
function renderFax(d){
  const el=document.getElementById("fax"), lg=document.getElementById("faxlog");
  if(!d||!d.ok){
    el.innerHTML=`<div class="banner bad"><b>Fax could not be read</b><code>${esc(d&&d.src||"/api/fax")}</code> — ${esc(d&&d.why||"?")}</div>`;
    lg.innerHTML=""; return;
  }
  const s=d.status, st_=s.stats||{};
  el.innerHTML=`<div class="grid">
    <div class="card"><div class="lbl">Trunk</div>
      ${s.trunk_registered?st("ok","registered"):st("bad","not registered")}
      ${s.trunk_available?st("ok","reachable"):st("warn","unreachable")}
      <div class="sub">voipms-fax · G.711 · T.38 refused by carrier</div></div>
    <div class="card"><div class="lbl">Engine</div>
      ${s.spandsp?st("ok","spandsp loaded"):st("bad","spandsp missing")}
      ${s.gs?st("ok","ghostscript"):st("bad","no ghostscript")}
      <div class="sub">${(s.active_sessions||[]).length} active session${(s.active_sessions||[]).length===1?"":"s"}</div></div>
    <div class="card"><div class="lbl">Since Asterisk started</div>
      <div class="mono">${st_["Transmit Attempts"]||0} attempted · ${st_["Completed FAXes"]||0} completed · ${st_["Failed FAXes"]||0} failed</div>
      <div class="sub">fax show stats</div></div>
    <div class="card"><div class="lbl">Fax machine (MX922 via OBi100)</div>
      ${s.obi100_registered?st("ok","ext 2007 registered"):st("na","ext 2007 absent")}
      <div class="sub">dial 8 + 1 + number from the machine</div></div>
  </div>`;
  const rows=d.log||[];
  lg.innerHTML=`<div class="scroll"><table><thead><tr>
    <th>Started</th><th>Dir</th><th>Number</th><th>Call</th><th class="mono">Secs</th><th>File</th></tr></thead><tbody>
    ${rows.map(r=>`<tr>
      <td class="mono">${esc((r.start_local||r.start||"").slice(5,16))}</td>
      <td>${esc(r.direction)}</td>
      <td class="mono">${esc(r.number||"—")}</td>
      <td class="disp-${esc(String(r.disposition||"").replace(/[^A-Z]/g,""))}">${esc(r.disposition)}</td>
      <td class="mono">${esc(r.billsec)}</td>
      <td class="mono">${esc(r.file||"")}</td></tr>`).join("")}
    </tbody></table></div>
    <p style="font-family:var(--serif);color:var(--ink2);font-size:.9rem;margin-top:10px">
    Fax calls from the CDR, newest first. <b>ANSWERED means the line connected;</b> delivery is
    what the counters above say, and <code>fax send --wait</code> reports it per send.</p>`;
}
async function loadFax(){
  try{ renderFax(await (await fetch("/api/fax",{cache:"no-store"})).json()); }
  catch(e){ renderFax({ok:false,src:"/api/fax",why:String(e)}); }
}
document.getElementById("faxsend").onclick = async () => {
  const b=document.getElementById("faxsend"), m=document.getElementById("faxmsg");
  const f=document.getElementById("faxfile").files[0];
  if(!f){ m.className="msg bad"; m.textContent="pick a PDF first"; return; }
  if(!document.getElementById("faxconfirm").checked){ m.className="msg bad"; m.textContent="tick the confirmation first"; return; }
  const fd=new FormData();
  fd.append("number",document.getElementById("faxnum").value);
  fd.append("label",document.getElementById("faxlabel").value);
  fd.append("confirm","yes");
  fd.append("file",f,f.name);
  b.disabled=true; m.className="msg"; m.textContent="converting and dialing…";
  try{
    const j=await (await authFetch("/api/fax/send",{method:"POST",
      intent:"send a fax to "+document.getElementById("faxnum").value, body:fd})).json();
    m.className="msg "+(j.ok?"good":"bad");
    m.textContent=(j.ok?"sent to Asterisk — ":"not sent — ")+(j.detail||"");
    if(j.ok){ document.getElementById("faxconfirm").checked=false; setTimeout(loadFax,5000); setTimeout(loadFax,60000); }
  }catch(e){ m.className="msg bad"; m.textContent="not sent — "+e; }
  b.disabled=false;
};

/* --- wiring --------------------------------------------------------- */
/* The last SUCCESSFUL read. Not the last attempt -- the distinction is the
   whole point: an attempt that failed tells you nothing about the network,
   only about the console. */
let LAST_OK = null;
function ago(ms){
  const t = Math.round((Date.now()-ms)/1000);
  if(t < 60) return t+"s ago";
  if(t < 3600) return Math.round(t/60)+"m ago";
  return Math.round(t/3600)+"h ago";
}
function freshness(ok, why){
  const el = document.getElementById("fresh");
  if(!el) return;
  if(ok){
    el.className = "rs-chip";
    el.innerHTML = "<i class=\"rs-mark ok\" aria-hidden=\"true\"></i>";
    el.appendChild(document.createTextNode("live"));
    el.title = "This snapshot was read by the request that drew the page.";
    return;
  }
  /* NOT a red alarm and NOT silence. The values on screen were true when they
     were read; what is unknown is whether they still are. Say exactly that,
     and say HOW OLD -- "ever" and "now" are the two this page must not blur. */
  /* FILLED, not hollow -- corrected when this moved to the shared block. The
     data on screen WAS measured; what is in doubt is its age, not its
     existence. Hollow is reserved for "nothing was measured at all", and
     spending it here would have left nothing to say that with. */
  el.className = "rs-chip stale";
  el.innerHTML = "<i class=\"rs-mark stale\" aria-hidden=\"true\"></i>";
  el.appendChild(document.createTextNode(
    LAST_OK ? ("stale \u00b7 last read " + ago(LAST_OK)) : "never read"));
  el.title = "The refresh is failing, so everything below is as it was at the "
           + "timestamp shown, not as it is now. Reason: " + why;
}
async function load(){
  let r, s;
  try{
    r = await fetch("/api/state", {cache:"no-store"});
    if(!r.ok) throw new Error("HTTP " + r.status);
    s = await r.json();
  }catch(e){
    /* Leave the previous snapshot on screen -- it is the best information
       available and blanking it would destroy the only record of what the
       network was doing. But STOP CALLING IT CURRENT. */
    freshness(false, String(e && e.message || e));
    return;
  }
  LAST_OK = Date.now();
  freshness(true);
  STATE=s;
  document.getElementById("host").textContent = s.host;
  document.getElementById("asof").textContent = s.as_of;
  /* ⛔ tileFemto() IS GONE, AND IT WAS WRONG IN TWO INDEPENDENT WAYS AT ONCE:
       1. SINGLE-AP BY CONSTRUCTION. It rendered /api/state's `femto`, from
          read_femtocell() (SINGULAR), whose grab() runs re.search over the WHOLE
          `show hnb` output and takes the FIRST match. With several HNBs registered
          it printed ONE cell's name, LAC, CID and SCTP state AS THOUGH THEY WERE
          "the femtocell". The others were not missing from the page; they were
          INVISIBLE TO THE PARSER. That is the owner's complaint, exactly.
       2. IT PAINTED LIVENESS FROM THE ASSOCIATION STATE, measured to read
          SCTP_ESTABLISHED for ~5 minutes after a cell leaves the network.
     ⇒ Every field it carried -- uptime, cell identity, Iuh peer, SCTP, contexts --
       is in "Cells and handsets" below, PER ACCESS POINT, with the path state that
       actually knows. Two panels that can disagree about one cell is strictly worse
       than one panel that cannot.
     ⚠️ /api/state still returns `femto` UNCHANGED. This removes a RENDERER, not a
       field: that contract is mirrored with :8080 and is not mine to narrow. */
  document.getElementById("live").innerHTML =
    tileTrunk(s.trunk)+tileCalls(s.calls)+tileServices(s.services);
  renderOverrides(s.overrides); renderPick(s); renderDir(s); renderCdr(s.cdr);
  /* ⭐ SEPARATE FETCH, DELIBERATELY NOT FOLDED INTO /api/state. snapshot() is a
     realm-sigil-adjacent contract mirrored with :8080; and a presence read that
     fails must not blank the trunk, the calls and the directory beside it. */
  /* ⭐ Census is behind a 90 s server cache and touches NO access point -- one
     HLR VTY read plus the local journal -- so it is safe on load. */
  /* ⛔ THE INDEX IS BUILT ONLY AFTER THESE RESOLVE, AND THAT IS NOT TIDINESS.
     These panels fill ASYNCHRONOUSLY and they are large -- the census alone
     renders 27 rows. An index built before they land computes its anchors
     against a page that is about to grow by thousands of pixels, so the first
     jump lands where the section USED TO BE. [measured in a real browser:
     clicking SMS landed on IMSI census, reproducibly, and ONLY for the first
     jump -- by the second the content had arrived. A fixed sleep did not fix
     it, which is what ruled out smooth scrolling as the cause.]
     ⭐ A link into a document that is still growing is not a navigation bug,
       it is a RACE, and it presents as an off-by-one-section that looks like a
       highlighting error. I nearly "fixed" the observer a second time.
     ⚠️ allSettled, not all: one failing panel must not cost the whole index.
     The anchors still work with no JS at all -- this only defers BUILDING the
     bar, and nothing about the page depends on it existing. */
  /* ⚠️ loadPresence IS IN THIS LIST, AND LEAVING IT OUT WAS THE BUG'S SECOND
     HALF. It renders "Cells and handsets", which sits ABOVE everything else, so
     when it lands every section below it shifts down. I deferred three of the
     four loaders and the symptom did not move AT ALL -- ⭐ A PARTIAL FIX TO A
     RACE IS INDISTINGUISHABLE FROM NO FIX, which is how I nearly concluded the
     deferral was the wrong idea and went back to blaming the observer a third
     time. ⇒ When a fix for a race changes nothing, check you fixed ALL of it
     before you check whether it was the right fix. */
  Promise.allSettled([loadPresence(), loadCensus(), loadVmail(), loadSms(),
                      loadNetdeps(), loadVoipms(), loadCells(), loadAcs(), loadFax()])
         .then(buildSectionIndex);
  document.getElementById("foot").innerHTML =
    `Every live value on this page carries the command that produced it &mdash;
     open <em>how this was read</em> on any tile. Where a state could not be read
     it says <b>not probed</b> rather than guessing, because a wrong green dot is
     believed and an honest gap is not.`;
}
document.getElementById("save").onclick = async () => {
  const b=document.getElementById("save"), m=document.getElementById("msg");
  b.disabled=true; m.className="msg"; m.textContent="saving…";
  try{
    const j = await (await authFetch("/api/save",{method:"POST",
      intent:"save which handsets ring on an inbound call",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({exts:picked()})})).json();
    m.className="msg "+(j.ok?"good":"bad");
    m.textContent=(j.ok?"saved — ":"not saved — ")+j.detail;
    if(j.ok) await load();
  }catch(e){ m.className="msg bad"; m.textContent="not saved — "+e; }
  b.disabled=false;
};
document.getElementById("refresh").onclick = load;
let timer=null;
function arm(){ clearInterval(timer);
  if(document.getElementById("auto").checked) timer=setInterval(load,20000); }
document.getElementById("auto").onchange = arm;
load(); arm();
</script></body></html>"""


# ---------------------------------------------------------------------------
# Fax -- a thin face over the `fax` CLI (~/Projects/fax, installed on this host
# by its scripts/deploy.sh as /usr/local/bin/fax). ALL fax logic lives there so
# the CLI and this panel cannot disagree about how a fax is sent or judged.
#
# Why shell out instead of importing: the CLI is the thing the owner runs by hand and
# the thing that was MEASURED (Faxbeep received the page, 2026-09-27 03:58 PDT);
# a copy of its logic here would drift the first time one of them is fixed.
#
# ⛔ A SEND IS OUTWARD-FACING: it dials a real number and delivers a document.
#    It is gated like every other write (X-Auth-Token) AND requires an explicit
#    confirm field, the same shape as the RF writes above.
# ---------------------------------------------------------------------------
FAX_CLI   = "/usr/local/bin/fax"
FAX_INBOX = os.path.join(os.environ.get("STATE_DIRECTORY", "/var/lib/telephony-console"), "fax")
FAX_MAX_BYTES = 15 * 1024 * 1024


def fax_cli(*args, timeout=40):
    """Run the fax CLI in --local --json mode. Never raises; failure is a dict."""
    try:
        r = subprocess.run([FAX_CLI, "--local", "--json", *args],
                           capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return {"ok": False, "src": FAX_CLI,
                "why": "fax CLI is not installed on this host -- run "
                       "~/Projects/fax/scripts/deploy.sh from the workstation"}
    except Exception as e:
        return {"ok": False, "src": FAX_CLI, "why": str(e)}
    if r.returncode != 0:
        return {"ok": False, "src": FAX_CLI,
                "why": (r.stderr or r.stdout).strip()[-400:] or f"exit {r.returncode}"}
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"ok": False, "src": FAX_CLI, "why": f"unparseable CLI output: {e}"}


def fax_state():
    st = fax_cli("status")
    lg = fax_cli("log", "--limit", "25")
    return {"ok": bool(st.get("ok")) and bool(lg.get("ok")),
            "status": st, "log": lg.get("rows", []),
            "why": st.get("why") or lg.get("why"),
            "src": FAX_CLI + " --local --json status | log --limit 25",
            "spool": "/var/spool/asterisk/fax", "inbox": FAX_INBOX}


def _multipart(content_type, body):
    """(fields, files) from a multipart/form-data body. files: name -> (filename, bytes)."""
    from email.parser import BytesParser
    from email.policy import default
    msg = BytesParser(policy=default).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
    fields, files = {}, {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition") or ""
        fn = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if fn:
            files[name] = (fn, payload)
        else:
            fields[name] = payload.decode("utf-8", "replace").strip()
    return fields, files


def fax_send(fields, files):
    """Validate, park the PDF under the state dir, hand it to the CLI. Returns the CLI's dict."""
    number = re.sub(r"\D", "", fields.get("number", ""))
    if len(number) == 10:
        number = "1" + number
    if len(number) != 11 or not number.startswith("1"):
        return {"ok": False, "detail": "number must be 10 digits (or 11 starting with 1)"}
    if number[1:4] in ("911", "988", "211", "311", "411", "511", "611", "711", "811"):
        return {"ok": False, "detail": "refusing an N11 number"}
    if "file" not in files:
        return {"ok": False, "detail": "no PDF attached"}
    fn, data = files["file"]
    if not data.startswith(b"%PDF-"):
        return {"ok": False, "detail": "only PDF files are accepted"}
    if len(data) > FAX_MAX_BYTES:
        return {"ok": False, "detail": "PDF larger than 15 MB"}
    label = re.sub(r"[^A-Za-z0-9_-]+", "-", fields.get("label") or os.path.splitext(fn)[0])[:40] or "fax"
    try:
        os.makedirs(FAX_INBOX, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(FAX_INBOX, f"{stamp}-{label}.pdf")
        with open(path, "wb") as fh:
            fh.write(data)
    except OSError as e:
        return {"ok": False, "detail": f"could not store the PDF: {e}"}
    r = fax_cli("send", path, number, "--label", label, timeout=90)
    if not r.get("ok"):
        return {"ok": False, "detail": r.get("why") or "the fax CLI refused"}
    r["detail"] = ("dialing %s with %s page(s); the outcome appears in the log below when the "
                   "call ends (judged by the fax counters, not the call disposition)"
                   % (number, r.get("pages", "?")))
    r["pdf"] = path
    return r


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Write authentication
# ---------------------------------------------------------------------------
# Reads stay open. Every do_POST route here is a write, and /api/radio reaches
# the transmit power of a live cell -- so do_POST is gated as a whole.
#
# FAILS CLOSED: no token in the environment refuses every write.

# ⭐ PORTED VERBATIM from web/exchange-status.py for the ONE-SERVER merge.
#   The owner knows :8080 by its tab icon — a brass switchboard jack — and after the
#   merge that URL is served by THIS program. The asset moves so the identity
#   of the page he types does not silently change.
# ⚠️ This does NOT change which icon any page DECLARES. Each page here still
#   carries its own inline data: URI, so nothing requests /favicon.svg unless
#   something asks for it directly. Preserving the asset is mechanical;
#   choosing which icon a merged page shows is a taste decision and not mine.
FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs><linearGradient id="b" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#f2d08a"/><stop offset=".5" stop-color="#c9973f"/>
<stop offset="1" stop-color="#8a6222"/></linearGradient></defs>
<rect width="64" height="64" rx="12" fill="#15181d"/>
<circle cx="32" cy="17" r="8" fill="url(#b)"/>
<rect x="27" y="23" width="10" height="17" fill="url(#b)"/>
<rect x="24" y="39" width="16" height="6" rx="2" fill="#e8c887"/>
<rect x="29" y="45" width="6" height="12" fill="#6f7d86"/>
<path d="M32 57 Q14 54 10 40" stroke="#c9973f" stroke-width="3" fill="none" stroke-linecap="round"/>
</svg>"""

AUTH_JS = r"""/* Write authentication for this page.
 *
 * READS ARE OPEN. WRITES carry an X-Auth-Token header. The token is held in
 * sessionStorage -- NOT localStorage -- so it dies with the tab. It is
 * deliberately not a cookie: nothing is attached automatically, so a
 * cross-site form POST cannot borrow it.
 *
 * =======================================================================
 *  THIS PYTHON STRING IS RAW ON PURPOSE -- AUTH_JS carries an r-prefix.
 * =======================================================================
 * It was NOT raw until 2026-09-11, and the \n escapes it contains were
 * therefore interpreted by PYTHON instead of surviving into the JavaScript.
 * That put REAL NEWLINES INSIDE JS STRING LITERALS, so /auth.js was a
 * SyntaxError, so window.authFetch was never defined, so EVERY WRITE ON
 * EVERY PAGE OF THIS CONSOLE failed as `ReferenceError: authFetch is not
 * defined` -- before one byte reached the server.
 *
 * It survived because it is INVISIBLE FROM THE SERVER SIDE. The browser
 * never sends the request, so the access log stays quiet and no WRITE
 * REFUSED line is ever logged: the server looks perfectly healthy, and the
 * journal's silence reads as "nobody tried" rather than "nobody could".
 * Nine days of logs showed 7 refusals, every one of them a curl.
 *
 * Found by fetching /auth.js and running `node --check` on the SERVED
 * BYTES, against a known-good and a known-bad control.
 * The page and the server disagreed about whether writes worked, and only
 * the BROWSER's copy was evidence.
 *
 * _auth_js_intact() in the server now detects this class of breakage and
 * serves a self-describing fallback instead of a bare ReferenceError.
 * =======================================================================
 *
 * NOTHING HERE ENFORCES ANYTHING. write_authorized() on the server is the
 * only gate, it fails closed, and this file does not touch it. This file
 * decides WHO IS ASKED, AND WHEN. It cannot widen what the server accepts.
 */
(function () {
  /* R-PREFIX CANARY. The two characters backslash and n, side by side, must
     survive from the Python source into this file. If the r-prefix on AUTH_JS
     is ever lost, Python collapses them into a real newline, this line stops
     matching, and _auth_js_intact() fails closed before a broken script can
     reach a browser. Do not "tidy" it away -- it is load-bearing. */
  var CANARY = "\n";
  var KEY  = "realm-write-token";
  var ITEM = "__ITEM__";
  var state = null;          /* cached /api/writes verdict */
  var pending = null;        /* the open unlock request, if any */

  function rd() { try { return sessionStorage.getItem(KEY) || ""; } catch (e) { return ""; } }
  function wr(v) { try { sessionStorage.setItem(KEY, v); } catch (e) {} }
  function rm() { try { sessionStorage.removeItem(KEY); } catch (e) {} }

  /* The PRE-FLIGHT VERDICT. read_dial() already applies this idea to the
     dialplan: showing the verdict BEFORE the user clicks save turns a refusal
     from a surprise into information. Cached, because it changes only when the
     server restarts -- but re-read on a 401, where it may have just changed. */
  async function verdict(force) {
    if (state && !force) return state;
    try {
      var r = await fetch("/api/writes", { cache: "no-store" });
      state = await r.json();
    } catch (e) {
      /* Unreachable is NOT the same as refused, and must never be rendered as
         a confident "writes unavailable" -- that is a verdict derived from no
         data. Say what actually happened. */
      state = { writable: null, mode: "unreachable", why: String(e) };
    }
    return state;
  }

  /* ---- the unlock bar -------------------------------------------------- */

  function css() {
    if (document.getElementById("wa-css")) return;
    var s = document.createElement("style");
    s.id = "wa-css";
    /* Every colour comes from the shared realm-tokens, so this inherits both
       themes from the page it is injected into and needs no dark-mode block of
       its own. Fallbacks are given because this script is also the one thing
       that must still work on a page whose CSS failed to load. */
    s.textContent = [
      '.wa-scrim{position:fixed;inset:0;background:rgba(20,14,4,.45);z-index:998;',
        'display:flex;align-items:center;justify-content:center;padding:20px}',
      '.wa-box{background:var(--panel,#fffdf8);color:var(--ink,#241f18);',
        'border:1px solid var(--line2,#c6b494);border-radius:var(--radius,10px);',
        'box-shadow:var(--shadow,0 10px 30px -12px rgba(0,0,0,.5));',
        'max-width:520px;width:100%;padding:20px 22px;',
        'font-family:var(--serif,Georgia,serif);font-size:15px;line-height:1.5}',
      '.wa-box h2{margin:0 0 6px;font-size:17px;font-weight:600}',
      '.wa-why{color:var(--ink2,#5c5244);margin:0 0 14px}',
      '.wa-intent{background:var(--brass-soft,#efe0c0);border-radius:var(--radius-sm,6px);',
        'padding:7px 10px;margin:0 0 14px;font-size:14px}',
      '.wa-box label{display:block;font-family:var(--mono,monospace);font-size:11px;',
        'letter-spacing:.08em;text-transform:uppercase;color:var(--ink2,#5c5244);margin:0 0 5px}',
      '.wa-row{display:flex;gap:8px}',
      '.wa-box input{flex:1;min-width:0;font-family:var(--mono,monospace);font-size:14px;',
        'padding:9px 11px;border:1px solid var(--line2,#c6b494);border-radius:var(--radius-sm,6px);',
        'background:var(--bg2,#fbf8f1);color:var(--ink,#241f18)}',
      '.wa-box input:focus{outline:2px solid var(--brass,#8a6222);outline-offset:1px}',
      '.wa-btn{font:inherit;font-size:14px;padding:9px 14px;cursor:pointer;',
        'border-radius:var(--radius-sm,6px);border:1px solid var(--line2,#c6b494);',
        'background:var(--bg2,#fbf8f1);color:var(--ink,#241f18)}',
      '.wa-btn:hover{border-color:var(--brass,#8a6222)}',
      '.wa-btn.pri{background:var(--brass,#8a6222);border-color:var(--brass,#8a6222);color:#fff}',
      '.wa-btn.pri:hover{background:var(--brass2,#a97c31)}',
      '.wa-foot{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}',
      '.wa-hint{font-size:13px;color:var(--ink2,#5c5244);margin:12px 0 0}',
      '.wa-hint code{font-family:var(--mono,monospace);background:var(--code-bg,#f0ead9);',
        'padding:1px 5px;border-radius:4px}',
      '.wa-err{color:var(--bad,#9c2f26);font-size:14px;margin:10px 0 0;min-height:1.2em}',
      '.wa-steps{margin:10px 0 0;padding-left:20px}',
      '.wa-steps li{margin:5px 0;font-family:var(--mono,monospace);font-size:13px;',
        'word-break:break-word}',
      /* the at-a-glance state, present on every page */
      '.wa-pill{position:fixed;left:12px;bottom:12px;z-index:997;display:inline-flex;',
        'align-items:center;gap:7px;font-family:var(--mono,monospace);font-size:11px;',
        'letter-spacing:.06em;text-transform:uppercase;padding:6px 11px;cursor:pointer;',
        'border-radius:999px;border:1px solid var(--line2,#c6b494);',
        'background:var(--panel,#fffdf8);color:var(--ink2,#5c5244);',
        'box-shadow:var(--shadow,0 2px 8px rgba(0,0,0,.15))}',
      '.wa-pill:hover{border-color:var(--brass,#8a6222);color:var(--ink,#241f18)}',
      '.wa-pill i{width:8px;height:8px;border-radius:50%;display:inline-block}',
      /* HOLLOW = not established, never a default green. Same three-verdict
         vocabulary the SIM ledger and the presence column already use. */
      '.wa-pill.locked i{border:2px solid var(--idle,#6b6355)}',
      '.wa-pill.open i{background:var(--ok,#2f6b41)}',
      '.wa-pill.none i{background:var(--bad,#9c2f26)}',
      '.wa-pill.unk i{border:2px solid var(--warn,#8a5a12)}',
      '@media (prefers-reduced-motion:no-preference){.wa-pill{transition:border-color .15s}}',
      '@media (max-width:560px){.wa-pill{font-size:10px;padding:5px 9px}}'
    ].join("");
    document.head.appendChild(s);
  }

  function close() {
    var s = document.querySelector(".wa-scrim");
    if (s) s.remove();
    if (pending && pending.last) { try { pending.last.focus(); } catch (e) {} }
  }

  /* Resolves with the token, or "" if the person declined. Never rejects:
     the caller decides what an empty answer means. */
  function ask(reason, intent) {
    css();
    close();
    return new Promise(function (resolve) {
      var v = state || {};
      var dead = v.mode === "refused";

      var scrim = document.createElement("div");
      scrim.className = "wa-scrim";
      var box = document.createElement("div");
      box.className = "wa-box";
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-modal", "true");
      box.setAttribute("aria-labelledby", "wa-h");
      scrim.appendChild(box);

      var h = document.createElement("h2");
      h.id = "wa-h";
      h.textContent = dead ? "Writes are unavailable on this server"
                           : "Unlock writes";
      box.appendChild(h);

      var why = document.createElement("p");
      why.className = "wa-why";
      why.textContent = reason || (dead
        ? (v.why || "This server holds no write token.")
        : "Writes on this console are protected by a token.");
      box.appendChild(why);

      /* WHAT IS WAITING. The old prompt() never said, so a refusal arriving
         mid-task left you guessing which action you were authorising. */
      if (intent) {
        var it = document.createElement("p");
        it.className = "wa-intent";
        it.textContent = "Waiting to " + intent;
        box.appendChild(it);
      }

      if (dead) {
        /* ASKING FOR A TOKEN HERE WOULD BE ASKING FOR A KEY TO A LOCK WITH NO
           KEYHOLE. The server holds none, so no value can succeed. Show the
           server-side remedy instead, as steps, and offer no input at all. */
        var ol = document.createElement("ol");
        ol.className = "wa-steps";
        (v.fix || []).forEach(function (step) {
          var li = document.createElement("li");
          li.textContent = step;
          ol.appendChild(li);
        });
        box.appendChild(ol);
        var f0 = document.createElement("div");
        f0.className = "wa-foot";
        var ok = document.createElement("button");
        ok.className = "wa-btn pri";
        ok.type = "button";
        ok.textContent = "Close";
        ok.onclick = function () { close(); resolve(""); };
        f0.appendChild(ok);
        box.appendChild(f0);
        document.body.appendChild(scrim);
        ok.focus();
        return;
      }

      var lab = document.createElement("label");
      lab.setAttribute("for", "wa-in");
      lab.textContent = "Console write token";
      box.appendChild(lab);

      var row = document.createElement("div");
      row.className = "wa-row";
      var inp = document.createElement("input");
      inp.id = "wa-in";
      inp.type = "password";
      inp.autocomplete = "off";
      inp.spellcheck = false;
      inp.setAttribute("aria-describedby", "wa-hint wa-err");
      row.appendChild(inp);
      var eye = document.createElement("button");
      eye.className = "wa-btn";
      eye.type = "button";
      eye.textContent = "Show";
      eye.setAttribute("aria-pressed", "false");
      eye.onclick = function () {
        var p = inp.type === "password";
        inp.type = p ? "text" : "password";
        eye.textContent = p ? "Hide" : "Show";
        eye.setAttribute("aria-pressed", p ? "true" : "false");
        inp.focus();
      };
      row.appendChild(eye);
      box.appendChild(row);

      var err = document.createElement("p");
      err.className = "wa-err";
      err.id = "wa-err";
      /* polite, not assertive: it is a correction to a field the person is
         already looking at, not an interruption. */
      err.setAttribute("aria-live", "polite");
      box.appendChild(err);

      var hint = document.createElement("p");
      hint.className = "wa-hint";
      hint.id = "wa-hint";
      hint.innerHTML = "Vaultwarden item <code></code>. Kept for this tab only" +
                       " and cleared when it closes. Reads never need it.";
      hint.querySelector("code").textContent = ITEM;
      box.appendChild(hint);

      var foot = document.createElement("div");
      foot.className = "wa-foot";
      var cancel = document.createElement("button");
      cancel.className = "wa-btn";
      cancel.type = "button";
      cancel.textContent = "Cancel";
      cancel.onclick = function () { close(); resolve(""); };
      var go = document.createElement("button");
      go.className = "wa-btn pri";
      go.type = "button";
      go.textContent = intent ? "Unlock and continue" : "Unlock";
      go.onclick = function () {
        var t = (inp.value || "").trim();
        if (!t) { err.textContent = "Enter the token, or cancel."; inp.focus(); return; }
        wr(t);
        close();
        resolve(t);
      };
      foot.appendChild(cancel);
      foot.appendChild(go);
      box.appendChild(foot);

      scrim.addEventListener("keydown", function (e) {
        if (e.key === "Escape") { close(); resolve(""); }
        if (e.key === "Enter" && document.activeElement === inp) { e.preventDefault(); go.click(); }
      });
      /* Clicking the backdrop cancels -- but ONLY the backdrop. A drag that
         ends outside the box must not count as a click on it. */
      scrim.addEventListener("mousedown", function (e) {
        if (e.target === scrim) { close(); resolve(""); }
      });

      pending = { last: document.activeElement };
      document.body.appendChild(scrim);
      inp.focus();
    });
  }

  /* ---- the at-a-glance state ------------------------------------------- */

  async function pill(force) {
    css();
    var v = await verdict(force);
    var el = document.getElementById("wa-pill");
    if (!el) {
      el = document.createElement("button");
      el.id = "wa-pill";
      el.type = "button";
      document.body.appendChild(el);
    }
    var held = !!rd();
    var cls, txt, title;
    if (v.mode === "refused") {
      cls = "none"; txt = "writes unavailable";
      title = v.why || "This server holds no write token.";
    } else if (v.mode === "unreachable") {
      /* NOT rendered as locked or open. Nothing was checked, and "nothing
         checked" is not the same as "nothing wrong". */
      cls = "unk"; txt = "write state unknown";
      title = "Could not read /api/writes: " + (v.why || "?");
    } else if (held) {
      cls = "open"; txt = "writes unlocked";
      title = "A token is held for this tab. Click to forget it.";
    } else {
      cls = "locked"; txt = "writes locked";
      title = "Reads are open. Click to unlock writes for this tab.";
    }
    el.className = "wa-pill " + cls;
    el.title = title;
    el.setAttribute("aria-label", txt + " — " + title);
    el.innerHTML = "<i aria-hidden=\"true\"></i>";
    el.appendChild(document.createTextNode(txt));
    el.onclick = async function () {
      if (v.mode === "refused" || v.mode === "unreachable") { await ask(); return; }
      if (rd()) { rm(); pill(); return; }
      await ask();
      pill();
    };
  }

  /* ---- the public surface ---------------------------------------------- */

  window.clearWriteToken = function () { rm(); pill(); };
  window.writeState = verdict;

  /*  authFetch(url, opts) -- unchanged signature, so NO CALLER CHANGED.
   *
   *  opts.intent is optional and additive: a short phrase naming the action,
   *  shown while unlocking ("Waiting to save the SIM ledger").
   *
   *  THE PENDING WRITE IS REPLAYED. Because this is async and every caller
   *  already awaits it, awaiting the unlock here resumes the ORIGINAL
   *  request. The 2026-09-11 failure it closes: a SIM was moved from a
   *  retired iPhone 4S into an iPad; the page detected the iPad from the air,
   *  computed the mismatch, offered the right button -- and then threw the
   *  action away at the auth step. The page knew the answer and could not
   *  act on it.
   */
  window.authFetch = async function (url, opts) {
    opts = opts || {};
    var intent = opts.intent || "";

    /* Ask the server FIRST whether a write can succeed at all. If it holds no
       token, no value the person types can work, so they are shown the
       server-side remedy instead of being made to guess a secret. */
    var v = await verdict();
    if (v.mode === "refused") {
      await ask(null, intent);
      throw new Error(v.why || "this server holds no write token");
    }

    var tok = rd() || await ask(null, intent);
    if (!tok) throw new Error("cancelled -- nothing was sent");

    function go(t) {
      var h = Object.assign({}, opts.headers || {}, { "X-Auth-Token": t });
      var o = Object.assign({}, opts, { headers: h });
      delete o.intent;   /* never let it reach fetch() as an unknown option */
      return fetch(url, o);
    }

    var r = await go(tok);
    if (r.status === 401) {
      rm();
      /* Re-read: the server may have been restarted without a token since the
         verdict was cached, in which case asking again is pointless. */
      var v2 = await verdict(true);
      pill();
      if (v2.mode === "refused") {
        await ask(null, intent);
        throw new Error(v2.why || "this server holds no write token");
      }
      var t2 = await ask("That token was refused. Try again?", intent);
      if (!t2) throw new Error("cancelled after a refusal -- nothing was saved");
      r = await go(t2);
      if (r.status === 401) {
        rm();
        pill();
        throw new Error("that token was refused twice -- check the Vaultwarden item " + ITEM);
      }
    }
    pill();
    return r;
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { pill(); });
  } else {
    pill();
  }
})();
"""


# ---------------------------------------------------------------------------
# A MECHANISM, NOT A MEMO.
#
# This corpus's own standing rule: prefer a mechanism over a law that asks a
# human to remember. The banner inside AUTH_JS explains the 2026-09-11 bug --
# the missing r-prefix that let PYTHON eat the escapes meant for JavaScript,
# put real newlines inside JS string literals, and made /auth.js a SyntaxError
# for its entire life. The next person to edit that string will not have read
# the banner. This function is what actually catches them.
#
# THE FAILURE WAS INVISIBLE FROM THE SERVER SIDE, which is exactly why it needs
# a mechanism rather than vigilance: a browser that cannot parse /auth.js never
# sends the write, so the access log stays quiet, no WRITE REFUSED line is ever
# logged, and the server looks healthy. The silence reads as "nobody tried" and
# actually means "nobody could". Nine days of journal held 7 refusals, every one
# of them a curl.
# ---------------------------------------------------------------------------

def _auth_js_intact(js: str = None) -> bool:
    """True if AUTH_JS still looks like JavaScript rather than Python output.

    Checks the CANARY line that AUTH_JS carries for this purpose: the two
    characters backslash and n, side by side, inside a JS string literal. They
    survive a raw string unchanged; lose the r-prefix and Python collapses them
    into a real newline, the literal below stops matching, and this returns
    False before a broken script can reach a browser.

    A heuristic was tried first and REJECTED, which is worth recording because
    it is the more obvious design: "no code line has an odd number of double
    quotes". It false-positived immediately, on a wrapped line of comment prose
    reading `checked" is not the same as "nothing wrong"`. Shipping it would
    have made every build serve the fallback and disabled writes permanently --
    the exact failure it was written to prevent, arrived at from the other side.
    An exact canary has no such failure mode.
    """
    js = AUTH_JS if js is None else js
    return 'var CANARY = "\\n";' in js


# Served INSTEAD of a corrupt AUTH_JS. Deliberately tiny, quote-light and
# escape-free, so it cannot fall to the very bug it exists to report.
#
# IT STILL DEFINES authFetch, AND authFetch STILL REFUSES. A page whose auth
# script failed to load must not quietly fall back to unauthenticated writes --
# it must fail closed AND SAY SO. The bare "ReferenceError: authFetch is not
# defined" this replaces told the user nothing and told the server nothing.
AUTH_JS_FALLBACK = r"""/* telephony-console: AUTH SCRIPT IS CORRUPT -- see _auth_js_intact() */
(function () {
  var MSG = "This console was built with a corrupt auth script, so writes are "
          + "disabled. Server-side fix: AUTH_JS in telephony-console.py must be "
          + "a raw string (r-prefix) -- see _auth_js_intact().";
  function banner() {
    if (document.getElementById("wa-broken")) return;
    var d = document.createElement("div");
    d.id = "wa-broken";
    d.setAttribute("role", "alert");
    d.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:999;"
      + "padding:10px 14px;font:13px/1.45 ui-monospace,monospace;"
      + "background:var(--bad-bg,#f7e2df);color:var(--bad,#9c2f26);"
      + "border-top:2px solid var(--bad,#9c2f26)";
    d.textContent = MSG;
    document.body.appendChild(d);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", banner);
  } else { banner(); }
  window.clearWriteToken = function () {};
  window.writeState = function () {
    return Promise.resolve({ writable: false, mode: "broken", why: MSG });
  };
  window.authFetch = function () { banner(); return Promise.reject(new Error(MSG)); };
})();
"""


# The Vaultwarden item that holds the write token. Named ONCE here and handed
# to the page, so the console and the vault cannot drift apart by a rename that
# only edits one of them.
AUTH_ITEM = "telephony-console-write-token"


def writes_state() -> dict:
    """Whether a write would be accepted, and why not if not.

    ⭐ This is read_dial()'s idea generalised. That function already returns a
    `writable` + `why` pre-flight verdict for the dialplan, on the reasoning
    that "showing the verdict BEFORE the user clicks save turns a refusal from
    a surprise into information". Every write on every page of this console
    passes through ONE gate -- write_authorized() -- and that gate had no such
    verdict, so the only way to discover it was to do all the work and then be
    refused. Same vocabulary deliberately: `writable`/`why`, not a second one
    invented for the same question.

    ⛔ THE TWO REFUSALS ARE NOT THE SAME REFUSAL, and conflating them is the
    dead-end this endpoint exists to close:
        mode "token"    the server HOLDS a token -- supplying it will work
        mode "refused"  the server holds NONE   -- no token can ever work,
                        and prompting a person for one is asking them to
                        produce a key to a lock with no keyhole.
    """
    if not write_token():
        return {
            "writable": False,
            "mode": "refused",
            "why": "this server holds no write token, so no write can succeed "
                   "-- entering a token here cannot help.",
            # Carried as STEPS, not one run-on sentence. The remedy is a
            # server-side action at a terminal, and the page should not have to
            # re-break prose to show it as a checklist. The 401 body keeps its
            # own verbatim copy so an API caller that never loads the page is
            # not left worse off than the page.
            "fix": [
                "Set TELEPHONY_CONSOLE_TOKEN=<token> in /etc/telephony-console.env",
                "Vaultwarden item: " + AUTH_ITEM,
                "systemctl restart telephony-console",
            ],
            "item": AUTH_ITEM,
        }
    return {"writable": True, "mode": "token", "why": None, "item": AUTH_ITEM}


def write_token() -> str:
    """The expected token, read per call rather than held in a global."""
    return (os.environ.get("TELEPHONY_CONSOLE_TOKEN") or "").strip()


def html_escape(t):
    """Minimal server-side escaper. The page JS has esc(); Python had none, and
    _doc_error interpolates a filesystem path, an OSError string, and self.path.

    ⛔ LOAD-BEARING. DO NOT REMOVE. MEASURED, and it corrects an earlier claim of
    mine that said the opposite.

    I first probed the 404 with a percent-encoded path (%3Cscript%3E) and got
    no raw script tag AND NO ESCAPED ONE -- the second half being the tell that
    the probe had not exercised anything. I concluded self.path is never
    URL-decoded, so the escaping was correct but decorative. ⇒ THAT CONCLUSION
    WAS WRONG, and it was wrong because the PROBE encoded the input, not because
    the server decodes it.

    A raw byte in the request target reaches self.path verbatim:

        curl --path-as-is 'http://host/<script>alert(1)</script>'
          -> raw "<script>alert" in response : 0
          -> "&lt;script&gt;" in response    : 1     <- THE ESCAPER FIRED
          -> rendered inside <code>: /&lt;script&gt;alert(1)&lt;/script&gt;

    ⇒ This function is the only thing standing between a hostile request target
    and reflected HTML on the 404 and the doc-missing pages. It is not a
    tidy-up, and it does not become load-bearing later -- it is load-bearing now.

    ⭐ A SECURITY PROBE MUST PROVE IT AROSE, not merely that nothing came back.
    Two ways to get a clean result that measured nothing, one from each of us:
      · mine SANITISED BEFORE SENDING (percent-encoded its own payload), so it
        proved the downstream escaper unnecessary by never testing it;
      · team-lead's probe with a raw SPACE in the path broke the HTTP request
        line -- HTTP 000, 0 bytes -- so the request never completed, and
        "nothing came back" was one keystroke from being reported as safe.
    ⛔ NEITHER FAILURE IS VISIBLE IN THE RESPONSE BODY. Both are visible in one
    line of transport metadata. ⇒ Make status and byte count part of the
    assertion, and reflect a CANARY first to prove reflection happens at all.

    ⚠️ CONTEXT BOUND, CLOSED BY MECHANISM RATHER THAN BY WARNING. All five call
    sites today put the output in ELEMENT TEXT (inside <code>...</code>), where
    an unescaped apostrophe is inert. That is a property of the CALLERS, not of
    this function, and it would break silently the moment someone reused it
    inside a single-quoted attribute. So "'" is escaped too -- harmless in text,
    necessary in an attribute -- and the helper is safe in both contexts instead
    of safe-if-you-remember. (Matches the page's JS esc(), which already did.)
    """
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;")
            .replace("'", "&#39;"))


class H(BaseHTTPRequestHandler):
    server_version = "telephony-console"

    def _send(self, code, body, ctype="application/json", extra=None):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        # Sending NO cache headers on an HTTP/1.0 response leaves browsers to
        # apply heuristic caching, so a page updated on the server keeps
        # rendering the visitor an old copy. From their side that is
        # indistinguishable from "it was never deployed" -- which is exactly
        # how it was reported on 2026-09-05, for a Sources page that was live,
        # linked in the nav, and serving 25985 bytes the whole time.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(b)
        except BrokenPipeError:
            pass

    def log_message(self, *a):
        # ⛔ STILL SILENT ON THE JOURNAL -- this page auto-refreshes every 20 s
        #   across a dozen endpoints and would bury every other unit on the host.
        # ⭐⭐ BUT THE TALLY BELOW EXISTS BECAUSE THE CONSOLIDATION DESTROYED AN
        #   INSTRUMENT AND I DID NOT NOTICE UNTIL AFTER THE SWITCH.
        #   exchange-status logged every request -- 18,315 GET lines in 7 days --
        #   and that access log is what settled, in one evening:
        #     · /api/status has ZERO external consumers (19 calls, all from the workstation)
        #     · Home Assistant keys on exactly ONE path (9,858 × /api/ha)
        #     · realm-testpage's zero is a WINDOW, not a fact
        #   ⇒ Retiring it left the survivor unable to answer "who is using this?",
        #     and I had already promised to retire :8092 "when the access log says
        #     nothing is using it" -- A MEASUREMENT PROMISED WITH AN INSTRUMENT
        #     THE SAME CHANGE REMOVED.
        #   ⚠️ NO GATE COULD HAVE CAUGHT THIS. Every gate compares OUTPUT; this is
        #     a loss of OBSERVABILITY, which has no key in any payload.
        try:
            _consumer_note(self.client_address[0],
                           self.server.server_address[1],
                           self.path.split("?")[0])
        except Exception:
            pass   # a tally must never be able to break a response

    def _audio(self):
        """Serve one recording.

        Strictly bounded: the name must match SAFE_WAV (no slashes, no dots that
        could climb), and the resolved path must still be inside MONITOR. Both
        checks, not either -- the regex is the cheap filter and realpath is the
        one that actually holds if the regex is ever loosened.
        """
        from urllib.parse import unquote
        name = unquote(self.path[len("/audio/"):])
        if not SAFE_WAV.match(name):
            return self._send(400, json.dumps({"detail": "bad name"}))
        path = os.path.realpath(os.path.join(MONITOR, name))
        if os.path.dirname(path) != os.path.realpath(MONITOR) or not os.path.isfile(path):
            return self._send(404, json.dumps({"detail": "not found"}))
        try:
            data = open(path, "rb").read()
        except Exception as e:
            return self._send(403, json.dumps({"detail": str(e)}))
        rng = self.headers.get("Range")
        m = re.match(r'bytes=(\d+)-(\d*)', rng or "")
        if m:
            a = int(m.group(1)); z = int(m.group(2)) if m.group(2) else len(data) - 1
            z = min(z, len(data) - 1)
            return self._send(206, data[a:z + 1], "audio/wav",
                              {"Accept-Ranges": "bytes",
                               "Content-Range": f"bytes {a}-{z}/{len(data)}"})
        self._send(200, data, "audio/wav", {"Accept-Ranges": "bytes"})

    # A DOC PAGE'S ERROR SHELL. It used to be a bare <p> with no <head> beyond a
    # charset: no viewport, no favicon, no tokens -- so a "not deployed" page
    # rendered as unstyled white, flashing white in dark mode and losing the tab
    # icon. ⚠️ AND IT IS REACHED BY A WORKING NAV LINK: /build-guide, /runbooks
    # and /sources are all in the shared nav, so this is a NORMAL-USE path on any
    # host where a doc was not installed, not an edge case.
    # ⭐ An error page is still the product. Getting this wrong tells the reader
    # the site is broken, when the truth is that one file is missing.
    _DOC_ICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
                 "viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' "
                 "fill='%23141117'/%3E%3Cpath d='M8 7h11l5 5v13a2 2 0 0 1-2 2H8a2 2 0 0 "
                 "1-2-2V9a2 2 0 0 1 2-2z' fill='%23d3ac52'/%3E%3C/svg%3E")

    def _doc_error(self, code, title, lead, detail=""):
        html = ("<!doctype html><meta charset=utf-8>"
                "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
                "<title>" + title + "</title>"
                "<link rel=icon href=\"" + self._DOC_ICON + "\">"
                "<style>" + TOKENS_CSS +
                "body{background:var(--bg);color:var(--ink);margin:0;"
                "font:var(--t-md,15px)/1.55 var(--serif)}"
                ".w{max-width:640px;margin:0 auto;padding:56px 22px}"
                "h1{font-size:var(--t-xl,24px);margin:0 0 10px}"
                "p{color:var(--ink2);margin:0 0 14px}"
                "code{font-family:var(--mono);background:var(--code-bg);"
                "padding:1px 5px;border-radius:4px;word-break:break-all}"
                "a{color:var(--brass)}"
                "</style>"
                "<div class=w><h1>" + title + "</h1>"
                "<p>" + lead + "</p>" + (("<p>" + detail + "</p>") if detail else "") +
                "<p><a href=\"/\">&larr; Telephony console</a></p></div>")
        return self._send(code, html, "text/html; charset=utf-8")

    def _doc(self, spec):
        name, title = spec
        path = os.path.realpath(os.path.join(DOC_DIR, name))
        if os.path.dirname(path) != os.path.realpath(DOC_DIR) or not os.path.isfile(path):
            # NAME THE PATH. "not deployed" without it is the error message this
            # corpus has been bitten by repeatedly -- and the reader is the person
            # who has to go and look.
            return self._doc_error(
                404, title,
                title + " is not deployed on this host.",
                "Looked for <code>" + html_escape(name) + "</code> in <code>"
                + html_escape(DOC_DIR) + "</code>. This is a deployment gap, not a "
                "fault in the console — the rest of the site is unaffected.")
        try:
            with open(path, "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        except OSError as e:
            return self._doc_error(
                500, title, title + " is installed but could not be read.",
                "<code>" + html_escape(str(e)) + "</code>")

    def do_GET(self):
        if self.path == "/api/state":
            try:
                return self._send(200, json.dumps(snapshot()))
            except Exception as e:
                return self._send(500, json.dumps({"detail": str(e)}))
        if self.path.startswith("/audio/"):
            return self._audio()
        if self.path == "/api/version":
            return self._send(200, json.dumps(version_dict()))
        if self.path == "/favicon.svg":
            # ⭐ :8080 serves this and :8092 did not (404). After the merge the owner's URL
            #   is served by this program, so the route moves with the asset.
            return self._send(200, FAVICON, ctype="image/svg+xml")
        # ⋯ [baseline elision: source lines 11180–11209 — cellular state routes (presence, status, cells, ACS)] ⋯
        if self.path == "/api/consumers":
            # ⭐ THE INSTRUMENT THE CONSOLIDATION REMOVED, rebuilt. This is what
            #   answers "is anything still using :8092?" — the question I
            #   promised to settle by measurement rather than by a date.
            return self._send(200, json.dumps(consumers_state()))
        if self.path == "/api/threads":
            # ⭐ THE THREAD RULE, MACHINE-READABLE. A gate reads this instead of
            #   grepping for `Thread(` -- which was the proxy that stopped
            #   tracking the property it stood in for.
            return self._send(200, json.dumps(background_thread_audit()))
        if self.path == "/api/voipms":
            # Cache only -- never an API call on a request path.
            return self._send(200, json.dumps(VOIPMS.snapshot()))
        # ⋯ [baseline elision: source lines 11223–11262 — Home Assistant, network-dependency, SMS, voicemail and census routes] ⋯
        if self.path == "/api/writes":
            # ⚠️ ADDITIVE, AND DELIBERATELY *NOT* A FIELD ON /api/version.
            # version_dict() is a realm-sigil contract mirrored field-for-field
            # with :8080 and monitored from checks.json; a new key there would
            # either break that mirror or force a matching edit in another
            # lane's file. A separate route changes no existing contract.
            #
            # ⛔ THIS LEAKS NOTHING NEW. It reports whether a token is
            # REQUIRED -- never the token, never whether a supplied one was
            # close, never a prefix. The same fact is already printed at
            # startup and is already inferable from any unauthenticated POST,
            # because the two 401 bodies differ precisely here. "refused" means
            # no write can succeed for anybody, which is not a fact worth
            # hiding; "token" still demands the secret.
            return self._send(200, json.dumps(writes_state()))
        if self.path == "/auth.js":
            # Fail closed AND VISIBLY. See _auth_js_intact().
            body = (AUTH_JS.replace("__ITEM__", AUTH_ITEM)
                    if _auth_js_intact() else AUTH_JS_FALLBACK)
            return self._send(200, body,
                              "application/javascript; charset=utf-8")
        # ⋯ [baseline elision: source lines 11284–11509 — matrix, inventory, radio, overview, femtocell, cell and band routes] ⋯
        if self.path == "/api/fax":
            return self._send(200, json.dumps(fax_state()))
        if self.path.rstrip("/") in DOCS:
            return self._doc(DOCS[self.path.rstrip("/")])
        if self.path.rstrip("/") in ("", "/"):
            return self._send(200, PAGE.replace("__TESTS__", json.dumps(TESTS))
                                       .replace("__TOKENS__", TOKENS_CSS)
                                       .replace("__STATUS__", STATUS_CSS),
                              "text/html; charset=utf-8")
        # ⛔ NOT a catch-all any more. Serving the console for every unknown path
        # meant a wrong nav link, or a route deployed to the wrong place, showed
        # a working-looking page instead of failing -- a 200 that proves nothing.
        # That is how an /api route silently fell through earlier tonight.
        # Uses the same shell as the doc fallback rather than a bare <p>.
        # morpheus-token argued against spending the bytes here, on the grounds
        # that nobody navigates to a 404 on purpose. ⇒ THE COMMENT DIRECTLY
        # ABOVE IS THE COUNTER-ARGUMENT, and it is this route's own stated
        # reason for existing: it catches "a wrong nav link, or a route deployed
        # to the wrong place". Both of those are a person who CLICKED something.
        # ⇒ The page that catches a broken link is not a place to stop looking
        # like the product -- it is where someone is already wondering whether
        # the site is broken.
        self._doc_error(404, "No such page",
                        "Nothing is served at <code>" + html_escape(self.path) + "</code>.",
                        "If you followed a link from this site, the link is wrong or the "
                        "route was deployed somewhere else — this is not a fault in the "
                        "page you came from.")
        return

    def write_authorized(self) -> bool:
        """Gate every write. Sends its own 401 and returns False on refusal.

        hmac.compare_digest, not ==, so the comparison cannot leak the prefix
        through timing. Compared as BYTES: compare_digest raises TypeError on
        a non-ASCII str, which would turn a refusal into a 500.

        Logs to stderr directly, NOT through log_message -- this class silences
        that entirely, so a refusal routed through it would leave no trace.
        ⛔ The supplied value is never logged, not even a prefix.
        """
        expected = write_token()
        supplied = (self.headers.get("X-Auth-Token") or "").strip()
        where = self.client_address[0] if self.client_address else "?"
        if not expected:
            print("telephony-console: WRITE REFUSED (server holds no token) "
                  "from %s %s" % (where, self.path), file=sys.stderr, flush=True)
            self._send(401, json.dumps({"ok": False, "detail":
                "write refused: this server has no write token configured. Set "
                "TELEPHONY_CONSOLE_TOKEN in /etc/telephony-console.env "
                "(Vaultwarden: telephony-console-write-token), then systemctl "
                "restart telephony-console."}))
            # Close rather than keep alive: this path returns without reading
            # the request body, and an unread body desyncs a reused connection.
            self.close_connection = True
            return False
        if not hmac.compare_digest(supplied.encode("utf-8"),
                                   expected.encode("utf-8")):
            print("telephony-console: WRITE REFUSED (missing or wrong "
                  "X-Auth-Token) from %s %s" % (where, self.path),
                  file=sys.stderr, flush=True)
            self._send(401, json.dumps({"ok": False, "detail":
                "write refused: missing or incorrect X-Auth-Token."}))
            # Close rather than keep alive: this path returns without reading
            # the request body, and an unread body desyncs a reused connection.
            self.close_connection = True
            return False
        return True

    def do_POST(self):
        # FIRST, before any route matching or body read: every route below is
        # a write, and one of them reaches a live radio.
        if not self.write_authorized():
            return
        if self.path == "/api/fax/send":
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n > FAX_MAX_BYTES + 65536:
                return self._send(413, json.dumps({"ok": False, "detail": "upload too large (15 MB max)"}))
            ctype = self.headers.get("Content-Type", "")
            if not ctype.startswith("multipart/form-data"):
                return self._send(400, json.dumps({"ok": False, "detail": "expected multipart/form-data"}))
            try:
                fields, files = _multipart(ctype, self.rfile.read(n))
            except Exception as e:
                return self._send(400, json.dumps({"ok": False, "detail": f"bad body: {e}"}))
            if fields.get("confirm") != "yes":
                return self._send(400, json.dumps({"ok": False, "detail":
                    "refused: this dials a real number and delivers a document, so it "
                    "requires an explicit confirmation"}))
            r = fax_send(fields, files)
            return self._send(200 if r.get("ok") else 400, json.dumps(r))
        # ⋯ [baseline elision: source lines 11600–11796 — RF and inventory writes (position, band, radio, SIM) and the dialplan save] ⋯


if __name__ == "__main__":
    import sys
    try:
        srv = ThreadingHTTPServer((BIND, PORT), H)
    except OSError as e:
        # Fail SAFE, never fail open: if the intended address is gone (renumbered
        # host, interface down) fall back to loopback rather than to 0.0.0.0.
        # A console nobody can reach is a much smaller problem than one everybody
        # can, and the message says plainly what happened.
        print(f"telephony-console: cannot bind {BIND}:{PORT} ({e}); "
              f"falling back to 127.0.0.1 -- reach it over an ssh tunnel",
              file=sys.stderr, flush=True)
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"telephony-console: listening on "
          f"{srv.server_address[0]}:{srv.server_address[1]}",
          file=sys.stderr, flush=True)
    # ── ADDITIONAL PORTS ────────────────────────────────────────────────────
    # ⭐ ONE PROCESS, SEVERAL PORTS -- NOT a second instance. During the
    #   consolidation the console answers on the RETIRED page's port and on its
    #   own, so every existing bookmark, script and tool keeps working while the
    #   switch settles.
    # ⛔ A SECOND *INSTANCE* WOULD BE TWO WRITERS AND ONE TRUTH: two VoIP.ms
    #   pollers writing one cache file, two DMI clients against a single-client
    #   console, two sets of caches disagreeing. One process with two listeners
    #   shares all of it by construction.
    # ⚠️ A FAILED EXTRA BIND IS REPORTED AND NOT FATAL. The primary port is the
    #   one that matters; losing a compatibility port must not take the console
    #   down with it. It is stated on stderr rather than swallowed, because an
    #   extra port that silently did not open looks exactly like one that did.
    _extra = [p.strip() for p in
              os.environ.get("TELEPHONY_CONSOLE_EXTRA_PORTS", "").split(",")
              if p.strip()]
    _extra_srv = []
    for _p in _extra:
        try:
            _s = ThreadingHTTPServer((BIND, int(_p)), H)
        except (OSError, ValueError) as e:
            print(f"telephony-console: EXTRA PORT {_p} NOT OPENED ({e}) -- the "
                  f"primary port is unaffected, but anything pointed at {_p} "
                  f"will get connection refused", file=sys.stderr, flush=True)
            continue
        _extra_srv.append(_s)
        start_background("listener", _s.serve_forever)
        print(f"telephony-console: also listening on "
              f"{_s.server_address[0]}:{_s.server_address[1]}",
              file=sys.stderr, flush=True)
    # ⛔ STARTED AFTER THE BIND SUCCEEDS, so a console that cannot take its port
    #   does not also start polling a third party.
    VOIPMS.start()
    _audit = background_thread_audit()
    print("telephony-console: background threads %s (%s)" % (
        "OK" if _audit["ok"] else "🔴 RULE VIOLATED",
        ", ".join("%s -> %s" % (k, v["touches"])
                  for k, v in _audit["registered"].items()) or "none"),
        file=sys.stderr, flush=True)
    print("telephony-console: writes %s" % (
        "require X-Auth-Token" if write_token()
        else "REFUSED -- no TELEPHONY_CONSOLE_TOKEN in the environment"),
        file=sys.stderr, flush=True)
    srv.serve_forever()
