"""faxcli.cdr — CDR parsing and fax-log derivation.

Pure functions except for utc_to_local which receives the timezone name
as a parameter (no os.environ access here).
"""
import csv
import datetime as dt
import io
import re

CDR = "/var/log/asterisk/cdr-csv/Master.csv"
TRUNK = "voipms-fax"

CDR_COLS = [
    "accountcode", "src", "dst", "dcontext", "clid", "channel", "dstchannel",
    "lastapp", "lastdata", "start", "answer", "end", "duration", "billsec",
    "disposition", "amaflags", "uniqueid", "userfield",
]


def parse_cdr(text: str, limit: int = 200) -> list[dict]:
    """Parse CSV text (Master.csv contents) into a list of row dicts.

    Returns at most *limit* rows from the tail of the file, matching legacy
    behaviour (cli.py:167: ``rows[-limit:]``).
    """
    rows = list(csv.reader(io.StringIO(text)))
    out = []
    for r in rows[-limit:]:
        if len(r) >= len(CDR_COLS):
            out.append(dict(zip(CDR_COLS, r, strict=False)))
    return out


def fax_rows(cdr: list[dict], tz: str = "America/Los_Angeles") -> list[dict]:
    """Derive fax-log rows from a list of CDR dicts.

    Matches legacy fax_rows (cli.py:173–192) exactly:
      - Filter to fax-related rows by lastapp, dcontext, channel, dstchannel.
      - Skip AppDial2 stub legs.
      - Derive file, direction, number, start_local.
      - Reverse (newest first).
    """
    rows = [
        r
        for r in cdr
        if r["lastapp"].lower() in ("sendfax", "receivefax")
        or r["dcontext"] == "from-fax"
        or TRUNK in r["channel"]
        or TRUNK in r["dstchannel"]
    ]
    result = []
    for r in rows:
        if r["lastapp"] == "AppDial2":  # the failed originate's stub leg — skip
            continue
        r = dict(r)  # don't mutate the input
        m = re.search(r"([^,/]+\.tiff?)", r["lastdata"])
        r["file"] = m.group(1) if m else ""
        r["direction"] = "in" if r["lastapp"].lower() == "receivefax" else "out"
        if r["dcontext"] == "from-fax":  # MX922 via the OBi: dialed 8/9 + number
            r["number"] = re.sub(r"^[89]", "", r["dst"])
        elif r["dst"] == "s":  # CLI originate: number is in the TIFF name
            m2 = re.search(r"-(1\d{10})\.tiff?$", r["file"])
            r["number"] = m2.group(1) if m2 else "?"
        else:
            r["number"] = r["dst"] or r["src"]
        r["start_local"] = utc_to_local(r["start"], tz)
        result.append(r)
    result.reverse()
    return result


def utc_to_local(s: str, tz: str) -> str:
    """Convert a UTC datetime string ``YYYY-MM-DD HH:MM:SS`` to local time.

    Returns the formatted string ``YYYY-MM-DD HH:MM``.  Falls back to the
    raw string on any error (mirrors legacy cli.py:202–203).

    The timezone name is a parameter so this function is pure and testable.
    """
    try:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(tz)
        t = dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
        return t.astimezone(zone).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return s
