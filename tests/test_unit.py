"""Unit tests for pure functions: numbers, asterisk, cdr, outcome, tiff."""
import struct
from pathlib import Path

import pytest

from faxcli.asterisk import (
    contact_available,
    module_loaded,
    parse_sessions,
    parse_stats,
    trunk_channel_up,
    trunk_registered,
)
from faxcli.cdr import fax_rows, parse_cdr, utc_to_local
from faxcli.numbers import InvalidNumber, normalize
from faxcli.outcome import judge
from faxcli.tiff import count_pages

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# numbers.normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_ten_digit_prepends_one(self):
        assert normalize("2025550100") == "12025550100"

    def test_eleven_digit_unchanged(self):
        assert normalize("12025550100") == "12025550100"

    def test_strips_punctuation(self):
        assert normalize("(202) 555-0100") == "12025550100"
        assert normalize("202.555.0100") == "12025550100"
        assert normalize("+1-202-555-0100") == "12025550100"

    def test_too_short_raises(self):
        with pytest.raises(InvalidNumber):
            normalize("555")

    def test_too_long_raises(self):
        # 13 digits — too many
        with pytest.raises(InvalidNumber):
            normalize("1" + "2025550100" + "22")

    def test_nine_digit_raises(self):
        with pytest.raises(InvalidNumber):
            normalize("202555010")

    def test_twelve_digit_raises(self):
        # 12 digits: not 10 or 11
        with pytest.raises(InvalidNumber):
            normalize("1" + "20255501000")

    def test_empty_raises(self):
        with pytest.raises(InvalidNumber):
            normalize("")

    def test_none_raises(self):
        with pytest.raises(InvalidNumber):
            normalize(None)  # type: ignore[arg-type]

    # All nine blocked codes (eight N11 codes + 988 crisis line)
    @pytest.mark.parametrize("code", ["911", "988", "211", "311", "411", "511", "611", "711", "811"])
    def test_blocked_codes(self, code):
        with pytest.raises(InvalidNumber, match="N11"):
            normalize(f"1{code}5550100")

    def test_valid_faxbeep(self):
        # Faxbeep is the one public test receiver exception
        assert normalize("1-972-532-9272") == "19725329272"

    def test_valid_fictional(self):
        assert normalize("12025550142") == "12025550142"


# ---------------------------------------------------------------------------
# asterisk.parse_stats
# ---------------------------------------------------------------------------

STATS_FIXTURE = """\

FAX Statistics:
---------------

Current Sessions     : 0
Reserved Sessions    : 0
Transmit Attempts    : 4
Receive Attempts     : 0
Completed FAXes      : 3
Failed FAXes         : 0

Spandsp G.711
Success              : 3
Switched to T.38     : 0
"""


class TestParseStats:
    def test_parses_fixture(self):
        stats = parse_stats(STATS_FIXTURE)
        assert stats["Transmit Attempts"] == 4
        assert stats["Completed FAXes"] == 3
        assert stats["Failed FAXes"] == 0
        assert stats["Success"] == 3

    def test_empty_string(self):
        assert parse_stats("") == {}

    def test_no_colon_lines_ignored(self):
        assert parse_stats("FAX Statistics:\n---------------\n") == {}

    def test_first_wins_on_duplicate(self):
        text = "Success              : 3\nSuccess              : 99\n"
        stats = parse_stats(text)
        assert stats["Success"] == 3  # setdefault keeps first

    def test_keys_stripped(self):
        stats = parse_stats("  Current Sessions     : 0\n")
        assert "Current Sessions" in stats

    def test_non_digit_values_ignored(self):
        stats = parse_stats("Version : abc\n")
        assert "Version" not in stats

    def test_real_fixture(self):
        text = (FIXTURES / "asterisk" / "fax_show_stats.txt").read_text()
        stats = parse_stats(text)
        assert stats["Transmit Attempts"] == 4
        assert stats["Completed FAXes"] == 3
        assert stats["Success"] == 3


# ---------------------------------------------------------------------------
# asterisk.parse_sessions
# ---------------------------------------------------------------------------

class TestParseSessions:
    def test_empty(self):
        assert parse_sessions("0 FAX sessions\n") == []

    def test_pjsip_line_included(self):
        text = "Channel\nPJSIP/voipms-fax-00000001\n0 FAX sessions\n"
        sessions = parse_sessions(text)
        assert sessions == ["PJSIP/voipms-fax-00000001"]

    def test_multiple(self):
        text = "PJSIP/a\nPJSIP/b\n0 FAX sessions\n"
        assert len(parse_sessions(text)) == 2

    def test_real_fixture_empty(self):
        text = (FIXTURES / "asterisk" / "fax_show_sessions.txt").read_text()
        assert parse_sessions(text) == []


# ---------------------------------------------------------------------------
# asterisk.trunk_registered / contact_available / module_loaded / trunk_channel_up
# ---------------------------------------------------------------------------

class TestAsteriskHelpers:
    def test_trunk_registered_true(self):
        assert trunk_registered("voipms/sip:pop1.example.com   Registered  (exp. 767s)")

    def test_trunk_registered_false(self):
        assert not trunk_registered("voipms/sip:pop1.example.com   Unregistered")

    def test_contact_available_voipms(self):
        line = "      Contact:  voipms/sip:pop1.example.com  4470b052f7 Avail  15.021"
        assert contact_available(line, "voipms")

    def test_contact_available_2007(self):
        line = "      Contact:  2007/sip:2007@192.0.2.131:5080  29d40da7be Avail  3.700"
        assert contact_available(line, "2007@")

    def test_contact_not_available(self):
        line = "      Contact:  voipms/sip:pop1.example.com  4470b052f7 Unavail  15.021"
        assert not contact_available(line, "voipms")

    def test_module_loaded(self):
        text = "res_fax_spandsp.so  Spandsp G.711 and T.38 FAX  0  Running"
        assert module_loaded(text, "res_fax_spandsp")

    def test_module_not_loaded(self):
        assert not module_loaded("res_fax.so  FAX  1  Running", "res_fax_spandsp")

    def test_trunk_channel_up(self):
        assert trunk_channel_up("PJSIP/voipms-fax-0001!Up!", "voipms-fax")

    def test_trunk_channel_not_up(self):
        assert not trunk_channel_up("PJSIP/2001-0001!Up!", "voipms-fax")

    def test_real_registrations_fixture(self):
        text = (FIXTURES / "asterisk" / "pjsip_show_registrations.txt").read_text()
        assert trunk_registered(text)

    def test_real_endpoint_voipms_fixture(self):
        text = (FIXTURES / "asterisk" / "pjsip_show_endpoint_voipms-fax.txt").read_text()
        assert contact_available(text, "voipms")

    def test_real_endpoint_2007_fixture(self):
        text = (FIXTURES / "asterisk" / "pjsip_show_endpoint_2007.txt").read_text()
        assert contact_available(text, "2007@")

    def test_real_module_fixture(self):
        text = (FIXTURES / "asterisk" / "module_show_like_res_fax.txt").read_text()
        assert module_loaded(text, "res_fax_spandsp")


# ---------------------------------------------------------------------------
# cdr.parse_cdr and cdr.fax_rows — using the real fixture
# ---------------------------------------------------------------------------

class TestCdrParsing:
    @pytest.fixture(scope="class")
    @classmethod
    def master_csv(cls):
        return (FIXTURES / "cdr" / "Master.csv").read_text()

    def test_parse_cdr_has_rows(self, master_csv):
        rows = parse_cdr(master_csv)
        assert len(rows) == 20  # 15 fax + 5 synthesized

    def test_fax_rows_count(self, master_csv):
        rows = parse_cdr(master_csv)
        fax = fax_rows(rows, "America/Los_Angeles")
        assert len(fax) == 14  # 15 fax rows, 1 AppDial2 removed

    def test_appdial2_excluded(self, master_csv):
        rows = parse_cdr(master_csv)
        fax = fax_rows(rows, "America/Los_Angeles")
        assert all(r["lastapp"] != "AppDial2" for r in fax)

    def test_newest_first(self, master_csv):
        rows = parse_cdr(master_csv)
        fax = fax_rows(rows, "America/Los_Angeles")
        starts = [r["start"] for r in fax]
        assert starts == sorted(starts, reverse=True)

    def test_number_extracted_from_tiff_name(self, master_csv):
        """SendFAX with a timestamp-number TIFF gets the number from the filename."""
        rows = parse_cdr(master_csv)
        fax = fax_rows(rows, "America/Los_Angeles")
        panel = [r for r in fax if "panel-test" in r.get("file", "")]
        assert panel, "expected panel-test row"
        assert panel[0]["number"] == "19725329272"

    def test_question_mark_when_no_number_in_tiff(self, master_csv):
        """SendFAX with a bare TIFF name (no number suffix) gets '?'."""
        rows = parse_cdr(master_csv)
        fax = fax_rows(rows, "America/Los_Angeles")
        bare = [r for r in fax if r.get("file") == "faxtest.tif"]
        assert bare, "expected faxtest.tif rows"
        for r in bare:
            assert r["number"] == "?"

    def test_mx922_prefix_strip_9(self, master_csv):
        """from-fax rows with dst starting in '9' have the prefix stripped."""
        rows = parse_cdr(master_csv)
        fax = fax_rows(rows, "America/Los_Angeles")
        from_fax_9 = [r for r in fax if r["dcontext"] == "from-fax" and r["dst"].startswith("9")]
        assert from_fax_9
        for r in from_fax_9:
            assert not r["number"].startswith("9")

    def test_mx922_prefix_strip_8(self, master_csv):
        """from-fax rows with dst starting in '8' have the prefix stripped."""
        rows = parse_cdr(master_csv)
        fax = fax_rows(rows, "America/Los_Angeles")
        from_fax_8 = [r for r in fax if r["dcontext"] == "from-fax" and r["dst"].startswith("8")]
        assert from_fax_8
        for r in from_fax_8:
            assert not r["number"].startswith("8")

    def test_start_local_format(self, master_csv):
        rows = parse_cdr(master_csv)
        fax = fax_rows(rows, "America/Los_Angeles")
        for r in fax:
            assert len(r["start_local"]) == 16  # "YYYY-MM-DD HH:MM"

    def test_derived_fields_present(self, master_csv):
        rows = parse_cdr(master_csv)
        fax = fax_rows(rows, "America/Los_Angeles")
        for r in fax:
            assert "file" in r
            assert "direction" in r
            assert "number" in r
            assert "start_local" in r


# ---------------------------------------------------------------------------
# cdr.utc_to_local
# ---------------------------------------------------------------------------

class TestUtcToLocal:
    def test_la_standard_time(self):
        # 2026-09-18 18:15:45 UTC is 11:15 PDT (UTC-7)
        result = utc_to_local("2026-09-18 18:15:45", "America/Los_Angeles")
        assert result == "2026-09-18 11:15"

    def test_date_line_crossing(self):
        # 2026-09-27 03:58:40 UTC is 2026-09-26 20:58 PDT (crosses date boundary)
        result = utc_to_local("2026-09-27 03:58:40", "America/Los_Angeles")
        assert result == "2026-09-26 20:58"

    def test_invalid_fallback(self):
        result = utc_to_local("not a date", "America/Los_Angeles")
        assert result == "not a date"

    def test_bad_tz_fallback(self):
        result = utc_to_local("2026-09-27 03:58:40", "Not/AZone")
        assert result == "2026-09-27 03:58:40"


# ---------------------------------------------------------------------------
# outcome.judge
# ---------------------------------------------------------------------------

class TestJudge:
    def test_sent(self):
        before = {"Completed FAXes": 2, "Failed FAXes": 0}
        after = {"Completed FAXes": 3, "Failed FAXes": 0}
        r = judge(before, after)
        assert r["outcome"] == "SENT"
        assert r["completed_delta"] == 1
        assert r["failed_delta"] == 0

    def test_failed(self):
        before = {"Completed FAXes": 2, "Failed FAXes": 0}
        after = {"Completed FAXes": 2, "Failed FAXes": 1}
        r = judge(before, after)
        assert r["outcome"] == "FAILED"
        assert r["failed_delta"] == 1

    def test_unknown(self):
        before = {"Completed FAXes": 2, "Failed FAXes": 0}
        after = {"Completed FAXes": 2, "Failed FAXes": 0}
        r = judge(before, after)
        assert r["outcome"] == "UNKNOWN"
        assert r["completed_delta"] == 0

    def test_empty_dicts(self):
        r = judge({}, {})
        assert r["outcome"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# tiff.count_pages
# ---------------------------------------------------------------------------

def _make_tiff(byte_order: str, pages: int) -> bytes:
    """Build a minimal multi-page TIFF in memory."""
    bo = byte_order  # "<" or ">"
    fmt_short = bo + "H"
    fmt_int = bo + "I"

    magic = b"II" if bo == "<" else b"MM"
    version = struct.pack(fmt_short, 42)

    # Each IFD: entry count (2) + 0 entries + next IFD offset (4)
    ifd_size = 2 + 4
    header_size = 8
    ifd_offsets = [header_size + i * ifd_size for i in range(pages)]

    header = magic + version + struct.pack(fmt_int, ifd_offsets[0])

    ifd_data = b""
    for i in range(pages):
        count = struct.pack(fmt_short, 0)
        next_off = ifd_offsets[i + 1] if i < pages - 1 else 0
        ifd_data += count + struct.pack(fmt_int, next_off)

    return header + ifd_data


class TestCountPages:
    def test_single_page_little_endian(self):
        data = _make_tiff("<", 1)
        assert count_pages(data) == 1

    def test_single_page_big_endian(self):
        data = _make_tiff(">", 1)
        assert count_pages(data) == 1

    def test_multi_page_little_endian(self):
        data = _make_tiff("<", 3)
        assert count_pages(data) == 3

    def test_multi_page_big_endian(self):
        data = _make_tiff(">", 4)
        assert count_pages(data) == 4

    def test_empty_bytes(self):
        assert count_pages(b"") == 0

    def test_garbage_bytes(self):
        assert count_pages(b"not a tiff at all") == 0

    def test_truncated(self):
        data = _make_tiff("<", 2)
        assert count_pages(data[:4]) == 0
