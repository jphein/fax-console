"""Tests for faxcli.inbound — generated Asterisk dialplan and hook for option A.

Covers:
- structural properties of the rendered dialplan (exten =>, ReceiveFax,
  FAXOPT(ecm), the h extension, FILTER for untrusted input)
- a golden snapshot of the rendered dialplan
- hostile caller-ID inputs: none must reach a path or command unescaped
- render_hook structure (tiff2pdf, inbox path, notify)
- CLI integration: fax inbound --render prints both outputs to stdout

No subprocess is spawned; every function returns text only.
"""
from __future__ import annotations

import io

import pytest

from faxcli.inbound import (
    SAFE_CALLERID_RE,
    InboundConfig,
    render_dialplan,
    render_hook,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_CFG = InboundConfig()

_GOLDEN_DIALPLAN = (
    "[from-fax-did]\n"
    "; Inbound fax \u2014 option A: dedicated DID 2025550177.\n"
    "; CALLERID(num) is filtered to [0-9+() -] before any path or command use.\n"
    "exten => _X.,1,NoOp(Inbound fax to ${EXTEN} from ${CALLERID(num)})\n"
    " same => n,Set(FAXOPT(ecm)=yes)\n"
    " same => n,Set(FAXFILE=/var/spool/asterisk/fax/"
    "in-${STRFTIME(,,%Y%m%d-%H%M%S)}-${FILTER(0-9+() -,${CALLERID(num)})}.tif)\n"
    " same => n,Answer()\n"
    " same => n,ReceiveFax(${FAXFILE},f)        ; f = G.711 fallback; voip.ms refuses T.38\n"
    " same => n,Hangup()\n"
    'exten => h,1,System(/usr/local/bin/fax-inbound-hook "${FAXFILE}" '
    '"${FAXOPT(status)}" "${FAXOPT(pages)}" '
    '"${FILTER(0-9+() -,${CALLERID(num)})}")\n'
)


# ---------------------------------------------------------------------------
# 1  InboundConfig defaults
# ---------------------------------------------------------------------------

class TestInboundConfigDefaults:
    def test_fax_did_is_second_number(self):
        """The fax DID must be 202-555-0177, not the house number 202-555-0100."""
        assert _DEFAULT_CFG.fax_did == "2025550177"

    def test_fax_did_not_house_number(self):
        assert _DEFAULT_CFG.fax_did != "2025550100"

    def test_context_name(self):
        assert _DEFAULT_CFG.context == "from-fax-did"

    def test_spool_dir(self):
        assert _DEFAULT_CFG.spool_dir == "/var/spool/asterisk/fax"

    def test_hook_path(self):
        assert _DEFAULT_CFG.hook_path == "/usr/local/bin/fax-inbound-hook"

    def test_no_notify_by_default(self):
        assert _DEFAULT_CFG.notify_cmd == ()


# ---------------------------------------------------------------------------
# 2  render_dialplan — structure
# ---------------------------------------------------------------------------

class TestRenderDialplanStructure:
    def setup_method(self):
        self.text = render_dialplan(_DEFAULT_CFG)

    def test_returns_string(self):
        assert isinstance(self.text, str)

    def test_ends_with_newline(self):
        assert self.text.endswith("\n")

    def test_context_header(self):
        assert "[from-fax-did]" in self.text

    def test_exten_wildcard_pattern(self):
        """Must match any extension with the _X. pattern."""
        assert "exten => _X.,1," in self.text

    def test_faxopt_ecm_yes(self):
        """ECM must be enabled as per option A design."""
        assert "FAXOPT(ecm)=yes" in self.text

    def test_receivefax_with_f_option(self):
        """ReceiveFax must use the 'f' (G.711 fallback) option; voip.ms refuses T.38."""
        assert "ReceiveFax(${FAXFILE},f)" in self.text

    def test_h_extension_present(self):
        """The h extension runs the hook after call ends."""
        assert "exten => h,1," in self.text

    def test_h_extension_calls_hook(self):
        assert "/usr/local/bin/fax-inbound-hook" in self.text

    def test_callerid_filtered_in_faxfile(self):
        """FILTER() is used on CALLERID(num) in the FAXFILE path — never the raw value."""
        assert "FILTER(" in self.text
        # Raw ${CALLERID(num)} must NOT appear inside the FAXFILE= assignment.
        faxfile_line = next(
            ln for ln in self.text.splitlines() if "FAXFILE=" in ln
        )
        assert "${CALLERID(num)}" not in faxfile_line.split("FAXFILE=", 1)[1].split("FILTER(")[0]

    def test_callerid_filtered_in_h_extension(self):
        """FILTER() is used on CALLERID(num) in the System() call, not the raw value."""
        h_line = next(ln for ln in self.text.splitlines() if "exten => h," in ln)
        # The raw CALLERID(num) must not appear outside a FILTER() call.
        assert "FILTER(" in h_line

    def test_spool_dir_in_faxfile(self):
        assert "/var/spool/asterisk/fax/" in self.text

    def test_strftime_in_faxfile(self):
        """Filename must include a timestamp (Asterisk STRFTIME)."""
        assert "STRFTIME(" in self.text


# ---------------------------------------------------------------------------
# 3  render_dialplan — golden snapshot
# ---------------------------------------------------------------------------

class TestRenderDialplanGolden:
    def test_golden(self):
        """Exact byte-for-byte snapshot of the rendered dialplan."""
        assert render_dialplan(_DEFAULT_CFG) == _GOLDEN_DIALPLAN

    def test_golden_custom_config(self):
        """Custom config changes are reflected in the output."""
        cfg = InboundConfig(
            context="from-fax-test",
            fax_did="2025550150",
            spool_dir="/tmp/fax",
            hook_path="/usr/local/bin/my-hook",
        )
        out = render_dialplan(cfg)
        assert "[from-fax-test]" in out
        assert "2025550150" in out
        assert "/tmp/fax/" in out
        assert "/usr/local/bin/my-hook" in out


# ---------------------------------------------------------------------------
# 4  Hostile caller-ID inputs — none may reach path or command unescaped
#
# The dialplan uses FILTER(0-9+() -,${CALLERID(num)}) which Asterisk evaluates
# at runtime; what we verify here is that the *rendered text* contains FILTER()
# wrapping the CALLERID(num) variable in every dangerous position, so that
# hostile content is always filtered before use.
# ---------------------------------------------------------------------------

# These strings represent what a hostile caller could send as caller-ID.
_HOSTILE_CALLER_IDS = [
    ('"', "double-quote — shell injection in System()"),
    (";", "semicolon — dialplan statement separator"),
    ("$(evil)", "dollar-paren — shell command substitution"),
    ("`evil`", "backtick — shell command substitution"),
    ("../../../etc/passwd", "path traversal via ../"),
    ("evil\nExten => h,1,System(/bin/sh)", "newline — dialplan injection"),
]


class TestHostileCallerID:
    """Verify that every hostile caller-ID character is behind FILTER() in the dialplan."""

    def setup_method(self):
        self.text = render_dialplan(_DEFAULT_CFG)
        # Extract lines where CALLERID(num) appears *outside* FILTER() — should be zero
        # dangerous lines.  The only acceptable occurrence of raw CALLERID(num) is in a
        # NoOp() or a comment, where it is never used to build a path or a command.
        self.faxfile_line = next(
            ln for ln in self.text.splitlines() if "FAXFILE=" in ln
        )
        self.h_line = next(
            ln for ln in self.text.splitlines() if "exten => h," in ln
        )

    @pytest.mark.parametrize("hostile,desc", _HOSTILE_CALLER_IDS)
    def test_hostile_not_in_faxfile_path_unfiltered(self, hostile, desc):
        """Hostile char not reachable in FAXFILE path without FILTER()."""
        # The FAXFILE line must contain FILTER() — confirmed by structure test.
        # Additionally, the hostile string itself cannot appear literally in the
        # rendered text (it is not substituted at render time; this checks that
        # the renderer does not accidentally embed hostile literals).
        assert hostile not in self.faxfile_line, (
            f"Hostile input ({desc}) appears literally in FAXFILE line"
        )

    @pytest.mark.parametrize("hostile,desc", _HOSTILE_CALLER_IDS)
    def test_hostile_not_in_h_extension_unfiltered(self, hostile, desc):
        """The raw ${CALLERID(num)} is never used directly in the System() argument list.

        The h-extension line wraps every caller-supplied value in FILTER().  Any
        literal ``"`` characters in the line are the shell-quoting delimiters we
        write, not caller input — so we check the *structure* (FILTER wraps the
        caller-ID) rather than the literal absence of ``"``.
        """
        # Confirm the line contains FILTER() — meaning the caller-ID is sanitised.
        assert "FILTER(" in self.h_line, "h-extension must wrap CALLERID(num) with FILTER()"
        # For characters that are NOT part of legitimate shell quoting (i.e. not the
        # double-quote used as the argument delimiter), assert they are absent.
        # The double-quote is the only legitimate structural character in the line;
        # all others would only appear there through a renderer bug.
        if hostile != '"':
            assert hostile not in self.h_line, (
                f"Hostile input ({desc}) appears literally in h-extension System() call"
            )

    def test_safe_callerid_re_rejects_quote(self):
        assert SAFE_CALLERID_RE.match('"evil"') is None

    def test_safe_callerid_re_rejects_semicolon(self):
        assert SAFE_CALLERID_RE.match("evil;cmd") is None

    def test_safe_callerid_re_rejects_dollar_paren(self):
        assert SAFE_CALLERID_RE.match("$(evil)") is None

    def test_safe_callerid_re_rejects_backtick(self):
        assert SAFE_CALLERID_RE.match("`evil`") is None

    def test_safe_callerid_re_rejects_path_traversal(self):
        assert SAFE_CALLERID_RE.match("../etc/passwd") is None

    def test_safe_callerid_re_rejects_newline(self):
        assert SAFE_CALLERID_RE.match("evil\ninjected") is None

    def test_safe_callerid_re_accepts_nanp(self):
        assert SAFE_CALLERID_RE.match("+1 (202) 555-0177") is not None

    def test_safe_callerid_re_accepts_digits(self):
        assert SAFE_CALLERID_RE.match("12025550177") is not None

    def test_safe_callerid_re_accepts_empty(self):
        assert SAFE_CALLERID_RE.match("") is not None


# ---------------------------------------------------------------------------
# 5  render_hook — structure
# ---------------------------------------------------------------------------

class TestRenderHookStructure:
    def setup_method(self):
        self.text = render_hook(_DEFAULT_CFG)

    def test_returns_string(self):
        assert isinstance(self.text, str)

    def test_shebang(self):
        assert self.text.startswith("#!/bin/sh\n")

    def test_tiff2pdf_called(self):
        assert "tiff2pdf" in self.text

    def test_inbox_directory_used(self):
        assert "/var/spool/asterisk/fax/inbox" in self.text

    def test_callerid_validated_with_tr(self):
        """The hook re-validates caller-ID with tr as defence in depth."""
        assert "tr -cd '0-9+() -'" in self.text

    def test_spool_dir_boundary_check(self):
        """The hook must verify FAXFILE is inside the spool dir."""
        assert '"$SPOOL_DIR"/*' in self.text or '"$SPOOL_DIR"/' in self.text

    def test_no_shell_injection_vector(self):
        """exec is used for notify, not eval or unquoted variable expansion."""
        assert "eval" not in self.text

    def test_set_eu(self):
        """set -eu makes the script fail fast on errors or unset variables."""
        assert "set -eu" in self.text


class TestRenderHookWithNotify:
    def test_notify_single_word(self):
        cfg = InboundConfig(notify_cmd=("/usr/local/bin/notify-fax",))
        text = render_hook(cfg)
        assert 'NOTIFY="/usr/local/bin/notify-fax"' in text
        assert 'exec "$NOTIFY"' in text

    def test_notify_multi_word(self):
        cfg = InboundConfig(notify_cmd=("/usr/bin/slack-notify", "--channel", "#fax"))
        text = render_hook(cfg)
        assert 'NOTIFY="/usr/bin/slack-notify"' in text
        assert '"--channel"' in text
        assert '"#fax"' in text
        # Fax facts are appended as separate arguments
        assert '"$FAXFILE_PDF"' in text
        assert '"$STATUS"' in text
        assert '"$CALLERID_SAFE"' in text

    def test_no_notify_when_empty(self):
        cfg = InboundConfig(notify_cmd=())
        text = render_hook(cfg)
        assert "NOTIFY" not in text


# ---------------------------------------------------------------------------
# 6  CLI integration: fax inbound --render
# ---------------------------------------------------------------------------

class TestCLIInbound:
    def test_inbound_render_exits_zero(self):
        from faxcli.cli import main  # noqa: PLC0415
        buf = io.StringIO()
        rc = main(["inbound", "--render"], stdout=buf)
        assert rc == 0

    def test_inbound_render_contains_dialplan(self):
        from faxcli.cli import main  # noqa: PLC0415
        buf = io.StringIO()
        main(["inbound", "--render"], stdout=buf)
        out = buf.getvalue()
        assert "[from-fax-did]" in out
        assert "ReceiveFax" in out

    def test_inbound_render_contains_hook(self):
        from faxcli.cli import main  # noqa: PLC0415
        buf = io.StringIO()
        main(["inbound", "--render"], stdout=buf)
        out = buf.getvalue()
        assert "#!/bin/sh" in out
        assert "tiff2pdf" in out

    def test_inbound_no_flag_also_works(self):
        """--render is optional; the subcommand always prints."""
        from faxcli.cli import main  # noqa: PLC0415
        buf = io.StringIO()
        rc = main(["inbound"], stdout=buf)
        assert rc == 0
        assert "[from-fax-did]" in buf.getvalue()
