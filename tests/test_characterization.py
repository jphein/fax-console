"""Characterization tests: frozen legacy module vs new faxcli package.

Imports legacy/fax/fax/cli.py read-only via importlib.util and drives it
with a fake subprocess.run backed by recorded fixtures.  Asserts that the
new package produces the same outputs for all inputs, with one explicit
exception: the deliberate ok:false change (Finding A, docs/analysis.md §9).

No real subprocess spawns happen.  Tests marked allow_subprocesses install
their own fake before any real call can occur.
"""
import importlib.util
import io
import json
import os
import struct as _struct
import sys
from pathlib import Path

import pytest

# ---- load the legacy module read-only ----

_LEGACY_PATH = Path(__file__).parent.parent / "legacy" / "fax" / "fax" / "cli.py"
_FIXTURES = Path(__file__).parent / "fixtures"


def _load_legacy():
    """Load legacy cli.py into a fresh module without importing it as a package."""
    spec = importlib.util.spec_from_file_location("legacy_cli", str(_LEGACY_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- fake subprocess.run that serves fixture files ----

class CompletedProcessStub:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _make_fake_run(fail_commands=None):
    """Return a fake subprocess.run that reads from the recorded fixtures."""
    fail_commands = fail_commands or set()

    def fake_run(argv, capture_output=False, text=False, timeout=None, check=False, **_kw):
        if not argv:
            return CompletedProcessStub(returncode=1)

        # asterisk -rx <cmd>  or sudo -n asterisk -rx <cmd>
        if "asterisk" in argv and "-rx" in argv:
            idx = argv.index("-rx")
            ast_cmd = argv[idx + 1]
            if ast_cmd in fail_commands:
                return CompletedProcessStub(returncode=1)
            fname = ast_cmd.replace(" ", "_") + ".txt"
            fpath = _FIXTURES / "asterisk" / fname
            if fpath.exists():
                return CompletedProcessStub(stdout=fpath.read_text())
            return CompletedProcessStub(returncode=1)

        # which gs
        if "which" in argv and "gs" in argv:
            return CompletedProcessStub(stdout="/usr/bin/gs\n")

        # tail -n <n> <cdr_path>
        if "tail" in argv:
            try:
                n_idx = argv.index("-n")
                limit = int(argv[n_idx + 1])
            except (ValueError, IndexError):
                limit = 200
            lines = (_FIXTURES / "cdr" / "Master.csv").read_text().splitlines()
            return CompletedProcessStub(stdout="\n".join(lines[-limit:]) + "\n")

        if check:
            raise Exception(f"unhandled check=True command: {argv}")
        return CompletedProcessStub(returncode=1)

    return fake_run


def _make_fake_open():
    """Return a fake open() that serves the CDR fixture when the CDR path is opened."""
    _real_open = open

    def fake_open(path, *args, **kwargs):
        from faxcli.cdr import CDR as CDR_PATH
        if str(path) == CDR_PATH:
            kwargs.pop("newline", None)
            return _real_open(str(_FIXTURES / "cdr" / "Master.csv"), *args, **kwargs)
        return _real_open(path, *args, **kwargs)

    return fake_open


# ---- test fixtures ----

@pytest.fixture(scope="module")
def legacy():
    return _load_legacy()


@pytest.fixture
def legacy_fake_run(legacy, monkeypatch):
    """Patch subprocess.run in the legacy module's subprocess reference."""
    monkeypatch.setattr(legacy.subprocess, "run", _make_fake_run())
    return legacy


@pytest.fixture
def legacy_fake_run_and_open(legacy, monkeypatch):
    """Patch subprocess.run AND builtins.open in the legacy module."""
    import builtins
    monkeypatch.setattr(legacy.subprocess, "run", _make_fake_run())
    monkeypatch.setattr(builtins, "open", _make_fake_open())
    return legacy


# ---- norm_number characterization ----

NORM_CORPUS = [
    ("2025550142", "12025550142"),
    ("12025550142", "12025550142"),
    ("(202) 555-0142", "12025550142"),
    ("202.555.0142", "12025550142"),
    ("+1-202-555-0142", "12025550142"),
    ("1-972-532-9272", "19725329272"),   # Faxbeep
]

NORM_INVALID = [
    "555",
    "",
    "12025",
    "1911" + "5550100",
    "1988" + "5550100",
]


class TestNormNumberCharacterization:
    @pytest.mark.parametrize("s,expected", NORM_CORPUS)
    def test_valid_agrees(self, legacy, s, expected):
        from faxcli.phone_numbers import normalize
        assert normalize(s) == expected
        result = legacy.norm_number(s)
        assert result == expected

    @pytest.mark.parametrize("s", NORM_INVALID)
    def test_invalid_both_reject(self, legacy, s):
        from faxcli.phone_numbers import InvalidNumber, normalize
        with pytest.raises(InvalidNumber):
            normalize(s)
        with pytest.raises(SystemExit):
            legacy.norm_number(s)

    @pytest.mark.parametrize("code", ["911", "988", "211", "311", "411", "511", "611", "711", "811"])
    def test_blocked_codes_both_reject(self, legacy, code):
        from faxcli.phone_numbers import InvalidNumber, normalize
        num = f"1{code}5550100"
        with pytest.raises(InvalidNumber):
            normalize(num)
        with pytest.raises(SystemExit):
            legacy.norm_number(num)


# ---- parse_stats characterization ----

class TestParseStatsCharacterization:
    def test_fixture_agrees(self, legacy):
        from faxcli.asterisk import parse_stats
        text = (_FIXTURES / "asterisk" / "fax_show_stats.txt").read_text()
        new_result = parse_stats(text)
        legacy_result = legacy.parse_stats(text)
        assert new_result == legacy_result

    def test_first_wins_duplicate(self, legacy):
        from faxcli.asterisk import parse_stats
        text = "Success : 3\nSuccess : 99\n"
        assert parse_stats(text) == legacy.parse_stats(text)
        assert parse_stats(text)["Success"] == 3


# ---- utc_to_local characterization ----

class TestUtcToLocalCharacterization:
    @pytest.mark.parametrize("s", [
        "2026-09-17 23:49:01",
        "2026-09-18 18:15:45",
        "2026-09-27 03:58:40",
        "2026-09-27 05:07:06",
        "not a date",
    ])
    def test_agrees(self, legacy, s):
        from faxcli.cdr import utc_to_local
        tz = os.environ.get("FAX_TZ", "America/Los_Angeles")
        new_result = utc_to_local(s, tz)
        legacy_result = legacy.utc_to_local(s)
        assert new_result == legacy_result


# ---- fax_rows characterization ----

class TestFaxRowsCharacterization:
    @pytest.mark.allow_subprocesses
    def test_row_count_agrees(self, legacy_fake_run_and_open):
        from faxcli.cdr import fax_rows, parse_cdr
        tz = os.environ.get("FAX_TZ", "America/Los_Angeles")
        text = (_FIXTURES / "cdr" / "Master.csv").read_text()
        new_rows = fax_rows(parse_cdr(text, 400), tz)
        legacy_rows = legacy_fake_run_and_open.fax_rows(local=True, limit=400)
        assert len(new_rows) == len(legacy_rows)

    @pytest.mark.allow_subprocesses
    def test_rows_agree_key_by_key(self, legacy_fake_run_and_open):
        from faxcli.cdr import fax_rows, parse_cdr
        tz = os.environ.get("FAX_TZ", "America/Los_Angeles")
        text = (_FIXTURES / "cdr" / "Master.csv").read_text()
        new_rows = fax_rows(parse_cdr(text, 400), tz)
        legacy_rows = legacy_fake_run_and_open.fax_rows(local=True, limit=400)
        for i, (new, leg) in enumerate(zip(new_rows, legacy_rows, strict=False)):
            for key in ("file", "direction", "number", "start_local",
                        "lastapp", "disposition", "billsec", "start"):
                assert new[key] == leg[key], (
                    f"row {i} key {key!r}: new={new[key]!r} legacy={leg[key]!r}"
                )


# ---- cmd_status JSON characterization ----

class TestCmdStatusCharacterization:
    @pytest.mark.allow_subprocesses
    def test_new_ok_true_matches_legacy_happy_path(self, legacy_fake_run):
        """On a healthy PBX (all reads succeed), new status JSON matches legacy
        for all fields.  Both should report ok:true on the recorded fixtures."""
        from faxcli.cli import main
        from faxcli.transport import ReplayTransport

        # New
        buf = io.StringIO()
        main(["--local", "--json", "status"], transport=ReplayTransport(), stdout=buf)
        new_obj = json.loads(buf.getvalue())

        # Legacy (--local so it reads CDR as file and runs asterisk locally)
        old_stdout = sys.stdout
        sys.stdout = buf2 = io.StringIO()
        try:
            legacy_fake_run.main(["--local", "--json", "status"])
        finally:
            sys.stdout = old_stdout
        leg_obj = json.loads(buf2.getvalue())

        assert new_obj["ok"] is True
        assert leg_obj["ok"] is True

        for key in ("spandsp", "trunk_registered", "trunk_available", "obi100_registered",
                    "active_sessions", "stats", "gs"):
            assert new_obj[key] == leg_obj[key], f"key {key!r} differs"


# ---- cmd_log JSON characterization ----

class TestCmdLogCharacterization:
    @pytest.mark.allow_subprocesses
    def test_log_rows_match_legacy(self, legacy_fake_run_and_open):
        from faxcli.cli import main
        from faxcli.transport import ReplayTransport

        # New
        buf = io.StringIO()
        main(["--local", "--json", "log", "--limit", "400"], transport=ReplayTransport(), stdout=buf)
        new_obj = json.loads(buf.getvalue())

        # Legacy
        old_stdout = sys.stdout
        sys.stdout = buf2 = io.StringIO()
        try:
            legacy_fake_run_and_open.main(["--local", "--json", "log", "--limit", "400"])
        finally:
            sys.stdout = old_stdout
        leg_obj = json.loads(buf2.getvalue())

        assert new_obj["ok"] is True
        assert leg_obj["ok"] is True
        assert len(new_obj["rows"]) == len(leg_obj["rows"])
        for i, (new_r, leg_r) in enumerate(zip(new_obj["rows"], leg_obj["rows"], strict=False)):
            for key in ("file", "direction", "number", "start_local",
                        "disposition", "billsec", "start", "lastapp"):
                assert new_r[key] == leg_r[key], (
                    f"row {i} key {key!r}: new={new_r[key]!r} legacy={leg_r[key]!r}"
                )


# ---- send --dry-run JSON characterization ----

def _write_minimal_tiff(path):
    """Write a valid 1-page little-endian TIFF to path."""
    bo = "<"
    magic = b"II"
    version = _struct.pack(bo + "H", 42)
    ifd_off = 8
    header = magic + version + _struct.pack(bo + "I", ifd_off)
    ifd = _struct.pack(bo + "H", 0) + _struct.pack(bo + "I", 0)
    with open(path, "wb") as f:
        f.write(header + ifd)


class TestCmdSendDryRunCharacterization:
    @pytest.mark.allow_subprocesses
    def test_dry_run_required_fields(self, legacy, tmp_path, monkeypatch):
        """New --dry-run output has the same required fields as legacy."""
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        # Patch legacy.SPOOL so the TIFF goes to tmp_path (not /var/spool/...)
        monkeypatch.setattr(legacy, "SPOOL", str(tmp_path))

        import subprocess as _sp

        # patch gs to write a 1-page TIFF to the output path
        def _gs_fake_run(argv, *a, **kw):
            if argv and argv[0] == "gs":
                for arg in argv:
                    if arg.startswith("-sOutputFile="):
                        out_path = arg[len("-sOutputFile="):]
                        _write_minimal_tiff(out_path)
                        break
                return CompletedProcessStub()
            if "which" in argv:
                return CompletedProcessStub(stdout="/usr/bin/gs\n")
            return CompletedProcessStub(returncode=1)

        monkeypatch.setattr(_sp, "run", _gs_fake_run)
        monkeypatch.setattr(legacy.subprocess, "run", _gs_fake_run)

        # Legacy (--local so no scp/ssh needed for dry-run too)
        old_stdout = sys.stdout
        sys.stdout = buf_leg = io.StringIO()
        try:
            legacy.main(["--local", "--json", "send", str(pdf), "12025550142", "--dry-run"])
        except SystemExit:
            pass
        finally:
            sys.stdout = old_stdout

        from faxcli.cli import main
        from faxcli.transport import ReplayTransport

        buf_new = io.StringIO()
        rc = main(
            ["--json", "send", str(pdf), "12025550142", "--dry-run"],
            transport=ReplayTransport(spool_dir=tmp_path),
            stdout=buf_new,
        )
        assert rc == 0

        new_obj = json.loads(buf_new.getvalue())
        leg_output = buf_leg.getvalue().strip()
        assert leg_output, "legacy produced no output"
        leg_obj = json.loads(leg_output.splitlines()[-1])

        for key in ("ok", "dry_run", "number", "pages"):
            assert key in new_obj, f"new missing {key!r}"
            assert key in leg_obj, f"legacy missing {key!r}"
            assert new_obj[key] == leg_obj[key], f"key {key!r} differs"


# ---- deliberate difference: ok:false when reads fail ----

class TestDeliberateDifference:
    """The ONE allowed difference between legacy and new: when all Asterisk reads fail,
    legacy says ok:true with zeroed fields; new must say ok:false."""

    @pytest.mark.allow_subprocesses
    def test_legacy_ok_true_on_failure(self, legacy, monkeypatch):
        """Confirm legacy behaviour: all-fail still returns ok:true (the bug being fixed)."""
        fail_cmds = {
            "fax show stats", "fax show sessions",
            "pjsip show endpoint voipms-fax", "pjsip show registrations",
            "pjsip show endpoint 2007", "module show like res_fax",
        }
        monkeypatch.setattr(legacy.subprocess, "run", _make_fake_run(fail_commands=fail_cmds))
        old_stdout = sys.stdout
        sys.stdout = buf = io.StringIO()
        try:
            legacy.main(["--local", "--json", "status"])
        finally:
            sys.stdout = old_stdout
        obj = json.loads(buf.getvalue())
        assert obj["ok"] is True  # legacy bug: reports ok even on failure

    def test_new_ok_false_on_failure(self):
        """New behaviour: all-fail returns ok:false with why and unread."""
        from faxcli.cli import main
        from faxcli.transport import ReplayTransport

        fail_cmds = {
            "fax show stats", "fax show sessions",
            "pjsip show endpoint voipms-fax", "pjsip show registrations",
            "pjsip show endpoint 2007", "module show like res_fax",
        }
        transport = ReplayTransport(fail_commands=fail_cmds)
        buf = io.StringIO()
        main(["--json", "status"], transport=transport, stdout=buf)
        obj = json.loads(buf.getvalue())
        assert obj["ok"] is False
        assert "why" in obj
        assert "unread" in obj
