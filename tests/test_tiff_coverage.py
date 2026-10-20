"""tests/test_tiff_coverage.py — edge-path coverage for faxcli.tiff.

Targets lines untouched by the existing suite:
  - count_pages: IFD offset points past end of data (line 29 — break out of loop)
  - count_pages: not enough bytes for next-IFD pointer (line 33 — break out of loop)
  - count_pages_from_path: file not found / I/O error (lines 46-47)
"""
from __future__ import annotations

import struct

from faxcli.tiff import count_pages, count_pages_from_path


def _make_tiff_header(byte_order: str, first_ifd_offset: int) -> bytes:
    """Return a minimal TIFF header pointing to first_ifd_offset."""
    bo = byte_order
    magic = b"II" if bo == "<" else b"MM"
    version = struct.pack(bo + "H", 42)
    offset = struct.pack(bo + "I", first_ifd_offset)
    return magic + version + offset


# ---------------------------------------------------------------------------
# count_pages — IFD offset points past end of data (line 29)
# ---------------------------------------------------------------------------

class TestCountPagesIfdBeyondEnd:
    def test_first_ifd_offset_beyond_end_returns_0(self):
        """An IFD offset that points past the end of the data must return 0."""
        # Header only (8 bytes), with IFD offset pointing to byte 100 (way past end)
        data = _make_tiff_header("<", 100)
        assert len(data) == 8
        result = count_pages(data)
        assert result == 0

    def test_ifd_offset_exactly_at_last_valid_byte_returns_0(self):
        """An IFD offset that leaves no room for entry count (2 bytes) returns 0."""
        # data is 9 bytes, IFD offset = 8: only 1 byte left, need 2
        data = _make_tiff_header("<", 8) + b"\x00"
        assert len(data) == 9
        result = count_pages(data)
        assert result == 0

    def test_big_endian_ifd_offset_beyond_end_returns_0(self):
        """Same test with big-endian byte order."""
        data = _make_tiff_header(">", 200)
        assert count_pages(data) == 0


# ---------------------------------------------------------------------------
# count_pages — not enough bytes for next-IFD pointer (line 33)
# ---------------------------------------------------------------------------

class TestCountPagesNextIfdPointerMissing:
    def test_ifd_has_entries_but_no_next_pointer(self):
        """An IFD whose entry array + next pointer would go past the end returns the
        pages counted so far (before the truncation)."""
        bo = "<"
        magic = b"II"
        version = struct.pack(bo + "H", 42)
        ifd_offset = 8
        header = magic + version + struct.pack(bo + "I", ifd_offset)

        # IFD: entry count = 5, but we don't include the 5*12 bytes of entries
        # → next_off_pos = 8 + 2 + 5*12 = 70, but total data length is only 12
        # so off + 2 > len is False (8+2=10 ≤ 12), but next_off_pos + 4 = 74 > 12
        ifd_data = struct.pack(bo + "H", 5)  # 2 bytes: entry count = 5
        data = header + ifd_data  # total: 10 bytes
        # off=8, off+2=10 ≤ 10, cnt=5, next_off_pos=8+2+60=70, 70+4=74 > 10 → break
        result = count_pages(data)
        assert result == 0  # broke before completing even page 1

    def test_one_full_page_then_truncated_next(self):
        """If the first IFD is complete but its next-IFD pointer area is truncated,
        only the first page is counted."""
        bo = "<"
        magic = b"II"
        version = struct.pack(bo + "H", 42)
        ifd_offset = 8
        header = magic + version + struct.pack(bo + "I", ifd_offset)

        # Valid IFD: entry count = 0, next IFD offset = some non-zero value, but
        # the bytes for that second IFD are not present.
        #
        # next_ifd_offset points to byte 14 (8 + 2 + 0*12 + 4 = 14), but we add
        # only 1 byte after the next-pointer so there aren't 2 bytes for the count.
        next_ifd = 14
        ifd_data = struct.pack(bo + "H", 0) + struct.pack(bo + "I", next_ifd)
        data = header + ifd_data + b"\x00"  # 1 stray byte at offset 14
        # Page 1 completes (off=8 → off=14), then off+2=16 > len=15 → break
        result = count_pages(data)
        assert result == 1


# ---------------------------------------------------------------------------
# count_pages_from_path — file not found
# ---------------------------------------------------------------------------

class TestCountPagesFromPath:
    def test_missing_file_returns_0(self, tmp_path):
        """count_pages_from_path must return 0 when the file does not exist."""
        result = count_pages_from_path(str(tmp_path / "nonexistent.tif"))
        assert result == 0

    def test_existing_valid_tiff_is_counted(self, tmp_path):
        """count_pages_from_path must delegate correctly to count_pages."""
        # Build a minimal 2-page little-endian TIFF
        bo = "<"
        magic = b"II"
        version = struct.pack(bo + "H", 42)
        ifd_size = 2 + 4  # entry count (0) + next-IFD offset
        ifd1_off = 8
        ifd2_off = ifd1_off + ifd_size
        header = magic + version + struct.pack(bo + "I", ifd1_off)
        ifd1 = struct.pack(bo + "H", 0) + struct.pack(bo + "I", ifd2_off)
        ifd2 = struct.pack(bo + "H", 0) + struct.pack(bo + "I", 0)
        data = header + ifd1 + ifd2

        f = tmp_path / "two_pages.tif"
        f.write_bytes(data)
        assert count_pages_from_path(str(f)) == 2
