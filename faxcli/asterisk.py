"""faxcli.asterisk — pure parsers over Asterisk CLI text.

All functions accept a text string (already fetched by the transport layer)
and return Python values.  No I/O, no subprocess.
"""
import re


def parse_stats(text: str) -> dict[str, int]:
    """Parse ``fax show stats`` output into {key: int}.

    The FIRST occurrence of a key wins (mirrors legacy setdefault behaviour,
    cli.py:211).  Lines that do not match ``Key : <digits>`` are ignored.
    """
    d: dict[str, int] = {}
    for line in text.splitlines():
        m = re.match(r"\s*([A-Za-z0-9. ]+?)\s*:\s*(\d+)\s*$", line)
        if m:
            k = m.group(1).strip()
            d.setdefault(k, int(m.group(2)))
    return d


def parse_sessions(text: str) -> list[str]:
    """Return lines that start with 'PJSIP' from ``fax show sessions`` output."""
    return [line for line in text.splitlines() if line.startswith("PJSIP")]


def trunk_registered(text: str) -> bool:
    """Return True if ``pjsip show registrations`` contains 'Registered'."""
    return "Registered" in text


def contact_available(text: str, pattern: str) -> bool:
    """Return True if the endpoint text contains a Contact line matching *pattern* and 'Avail'.

    The legacy checks are:
      trunk_available : re.search(r"Contact:.*voipms.*Avail", trunk)   cli.py:227
      obi100_registered: re.search(r"Contact:.*2007@.*Avail", obi)     cli.py:228
    """
    return bool(re.search(rf"Contact:.*{pattern}.*Avail", text))


def module_loaded(text: str, name: str) -> bool:
    """Return True if *name* appears in ``module show like …`` output."""
    return name in text


def trunk_channel_up(text: str, trunk: str) -> bool:
    """Return True if *trunk* appears in ``core show channels concise`` output."""
    return trunk in text
