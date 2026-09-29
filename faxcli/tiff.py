"""faxcli.tiff — count TIFF pages (IFDs) from bytes, without libtiff.

Mirrors legacy tiff_pages (cli.py:84–97).  Accepts bytes so tests can build
TIFF payloads in memory without touching the filesystem.
"""
import struct


def count_pages(data: bytes) -> int:
    """Count IFDs (pages) in a TIFF byte string.

    Returns 0 on any parse error, matching legacy behaviour (cli.py:96–97).
    Supports both little-endian (II) and big-endian (MM) byte orders.
    """
    try:
        if len(data) < 8:
            return 0
        magic = data[:2]
        if magic == b"II":
            bo = "<"
        elif magic == b"MM":
            bo = ">"
        else:
            return 0
        off = struct.unpack_from(bo + "I", data, 4)[0]
        n = 0
        while off and n < 10000:
            if off + 2 > len(data):
                break
            cnt = struct.unpack_from(bo + "H", data, off)[0]
            next_off_pos = off + 2 + cnt * 12
            if next_off_pos + 4 > len(data):
                break
            off = struct.unpack_from(bo + "I", data, next_off_pos)[0]
            n += 1
        return n
    except Exception:
        return 0


def count_pages_from_path(path: str) -> int:
    """Read *path* and delegate to count_pages.  Returns 0 on any I/O error."""
    try:
        with open(path, "rb") as f:
            return count_pages(f.read())
    except Exception:
        return 0
