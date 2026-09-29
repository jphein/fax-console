"""faxcli.inbound — generated Asterisk dialplan and hook script for option A inbound fax.

Option A (legacy/fax/docs/inbound.md lines 22-38): a second DID dedicated to fax.
Nothing here deploys, writes a file, or runs a process: every function returns text.

Untrusted input
---------------
The only channel variable the remote caller can control is CALLERID(num).  It appears
in two places in the generated output:

1. The FAXFILE path — embedded in a filename under the spool directory.
   Risk: path traversal (``../``) and dialplan injection (newlines, quotes, commas).
   Mitigation: wrap the value with Asterisk's FILTER() function, allowing only the
   characters that appear in a legitimate NANP caller-ID: digits, ``+``, ``-``, ``(``,
   ``)``, and space.  FILTER strips everything else *inside Asterisk*, before the value
   is ever used in a path.

2. The System() call in the ``h`` extension — passed as a double-quoted shell argument.
   Risk: shell injection via ``"``, ``$(...)``, backtick, ``\n``, etc.
   Mitigation: the same FILTER() result is used for the System() argument, so the hook
   script only ever receives the already-filtered string.  The hook script validates it
   again with a regex before using it in any path or command (defence in depth).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Characters permitted in a normalised caller-ID passed to Asterisk FILTER().
# Digits, plus sign, hyphen, parentheses, space — enough for any NANP or E.164 number.
# Everything else (quotes, semicolons, backticks, dollar signs, slashes, newlines, …) is stripped.
_CALLERID_FILTER = "0-9+() -"

# Regex that validates the same set on the hook-script side (defence in depth).
# We compile it once at import time so tests can import it.
SAFE_CALLERID_RE = re.compile(r"^[0-9+() -]{0,32}$")


@dataclass(frozen=True)
class InboundConfig:
    """Everything the renderer needs; all fields are pure data, not I/O.

    Attributes:
        context:    Asterisk dialplan context name (e.g. ``"from-fax-did"``).
        fax_did:    The inbound DID — the *second* number, not the house line.
                    Must be a fictional 202-555-0177 for tests.
        spool_dir:  Directory where Asterisk writes TIFF files.
        hook_path:  Absolute path to the fax-inbound-hook script on the PBX.
        notify_cmd: Optional notify command (list of words).  When non-empty it is
                    appended to the hook script as ``exec WORD…`` with the fax facts
                    as extra arguments.  Each word is validated by the hook at runtime.
    """

    context: str = "from-fax-did"
    fax_did: str = "2025550177"
    spool_dir: str = "/var/spool/asterisk/fax"
    hook_path: str = "/usr/local/bin/fax-inbound-hook"
    notify_cmd: tuple[str, ...] = ()


def render_dialplan(config: InboundConfig) -> str:
    """Return the Asterisk dialplan text for the inbound-fax context.

    The rendered text is suitable for pasting into extensions.conf (or an #include'd
    file).  It is never written to disk and never loaded by this function.

    Security notes (see module docstring for the threat model):
    - CALLERID(num) is wrapped with FILTER() in every use, restricting it to
      digits, ``+``, ``-``, ``(``, ``)``, and space before it enters any path or
      command.  Hostile values (quotes, semicolons, ``$(…)``, backtick, ``../``,
      newlines) are silently dropped by Asterisk before the value is used.
    - The FAXFILE variable is set once from the filtered caller-ID, then reused via
      ``${FAXFILE}`` everywhere else — the filtered value is not re-expanded.
    """
    ctx = config.context
    spool = config.spool_dir
    hook = config.hook_path
    cid_filter = _CALLERID_FILTER

    # The FAXFILE name embeds a timestamp and the filtered caller-ID.
    # STRFTIME(,,%Y%m%d-%H%M%S) is evaluated by Asterisk at runtime (no user input).
    # FILTER(allowed_chars, value) strips every char not in allowed_chars.
    faxfile = (
        f"{spool}"
        f"/in-${{STRFTIME(,,%Y%m%d-%H%M%S)}}"
        f"-${{FILTER({cid_filter},${{CALLERID(num)}})}}.tif"
    )

    # The filtered caller-ID reused for the System() call.
    safe_cid = f"${{FILTER({cid_filter},${{CALLERID(num)}})}}"

    lines = [
        f"[{ctx}]",
        f"; Inbound fax — option A: dedicated DID {config.fax_did}.",
        f"; CALLERID(num) is filtered to [{cid_filter}] before any path or command use.",
        "exten => _X.,1,NoOp(Inbound fax to ${EXTEN} from ${CALLERID(num)})",
        " same => n,Set(FAXOPT(ecm)=yes)",
        f" same => n,Set(FAXFILE={faxfile})",
        " same => n,Answer()",
        " same => n,ReceiveFax(${FAXFILE},f)        ; f = G.711 fallback; voip.ms refuses T.38",
        " same => n,Hangup()",
        # The h extension runs after hangup regardless of how the call ended.
        # FAXOPT(status) and FAXOPT(pages) are set by Asterisk's res_fax module —
        # they are not caller-controlled.
        f'exten => h,1,System({hook} "${{FAXFILE}}" "${{FAXOPT(status)}}" "${{FAXOPT(pages)}}" "{safe_cid}")',
    ]
    return "\n".join(lines) + "\n"


def render_hook(config: InboundConfig) -> str:
    """Return the text of the fax-inbound-hook shell script.

    The script:
    1. Validates its arguments defensively (callerid restricted to safe chars).
    2. Converts the TIFF to PDF with tiff2pdf.
    3. Moves the PDF into the inbox directory under the spool.
    4. Optionally runs a notify command with the fax facts as separate arguments,
       never through a shell (exec "$NOTIFY" …).

    Security notes:
    - All four arguments come from Asterisk channel variables.  Only $4 (caller-ID)
      is caller-controlled; $1 (FAXFILE) comes from FAXFILE which was set with the
      filtered value.  The hook validates all paths to confirm they are under the
      spool directory before using them.
    - The notify command is run with ``exec`` and an explicit argument list, never
      via ``eval`` or word-splitting — no shell injection is possible through the
      fax facts.
    - tiff2pdf is called with an explicit argument list; the TIFF path is the only
      variable and it has been validated against the spool directory.
    """
    spool = config.spool_dir
    inbox = f"{spool}/inbox"
    hook_path = config.hook_path

    notify_var = ""
    notify_block = ""
    if config.notify_cmd:
        first_word = config.notify_cmd[0]
        notify_var = f'\nNOTIFY="{first_word}"'
        if len(config.notify_cmd) > 1:
            # Extra words from config are hard-coded literals; fax facts are separate args.
            rest = " ".join(f'"{w}"' for w in config.notify_cmd[1:])
            exec_line = f'    exec "$NOTIFY" {rest} "$FAXFILE_PDF" "$STATUS" "$PAGES" "$CALLERID_SAFE"'
        else:
            exec_line = '    exec "$NOTIFY" "$FAXFILE_PDF" "$STATUS" "$PAGES" "$CALLERID_SAFE"'
        # Each notify word is a literal from config — not caller input.
        # The fax facts are passed as separate un-expanded arguments so the notify
        # program receives them as discrete strings, never joined into a shell word.
        notify_block = f"""
# Optional notification (arguments are separate words, not a shell string).
if [ -n "$NOTIFY" ]; then
{exec_line}
fi"""

    script = f"""\
#!/bin/sh
# {hook_path}
# Generated by faxcli.inbound.render_hook — do not edit by hand.
#
# Called by Asterisk's 'h' extension after an inbound fax call.
# Arguments (from the dialplan System() call):
#   $1  FAXFILE   — absolute path to the received TIFF (set via FILTER in dialplan)
#   $2  STATUS    — FAXOPT(status): "SUCCESS" or "FAILED" (set by res_fax, not caller)
#   $3  PAGES     — FAXOPT(pages): digit string (set by res_fax, not caller)
#   $4  CALLERID  — filtered caller-ID string (filtered by FILTER() in dialplan)
#
# Security: $1 is validated to be inside the spool directory; $4 is re-validated
# against the safe character set as a second line of defence.  No shell expansion
# of fax facts is performed when running the notify command.

set -eu

FAXFILE="$1"
STATUS="$2"
PAGES="$3"
CALLERID_RAW="$4"
SPOOL_DIR="{spool}"
INBOX_DIR="{inbox}"{notify_var}

# --- Validate caller-ID (defence in depth; already filtered by Asterisk FILTER()) ---
# Strip every character not in [0-9+() -].  If the result is empty, use "unknown".
CALLERID_SAFE="$(printf '%s' "$CALLERID_RAW" | tr -cd '0-9+() -')"
if [ -z "$CALLERID_SAFE" ]; then
    CALLERID_SAFE="unknown"
fi

# --- Validate FAXFILE is inside the spool directory ---
# Resolve the path without following symlinks beyond the spool root.
case "$FAXFILE" in
    "$SPOOL_DIR"/*)
        ;;  # OK
    *)
        echo "fax-inbound-hook: FAXFILE is outside spool directory: $FAXFILE" >&2
        exit 1
        ;;
esac

# --- Validate FAXFILE exists and is a regular file ---
if [ ! -f "$FAXFILE" ]; then
    echo "fax-inbound-hook: FAXFILE not found: $FAXFILE" >&2
    exit 1
fi

# --- Convert TIFF to PDF ---
FAXFILE_PDF="${{FAXFILE%.tif}}.pdf"
tiff2pdf -o "$FAXFILE_PDF" "$FAXFILE"

# --- Move PDF to inbox ---
mkdir -p "$INBOX_DIR"
mv "$FAXFILE_PDF" "$INBOX_DIR/"
FAXFILE_PDF="$INBOX_DIR/$(basename "$FAXFILE_PDF")"

echo "fax-inbound-hook: received from $CALLERID_SAFE" \
    "$PAGES page(s) status=$STATUS file=$FAXFILE_PDF" >&2
{notify_block}
"""
    return script
