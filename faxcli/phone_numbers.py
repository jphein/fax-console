"""faxcli.phone_numbers — phone-number normalisation.

Pure function; never exits the process. Callers (e.g. cli.py main()) catch
InvalidNumber and call sys.exit.

Renamed from numbers.py to avoid shadowing the stdlib ``numbers`` module when
any file in faxcli/ is run as a script.
"""
import re

# The nine blocked codes: eight N11 service codes plus 988 (crisis line).
_BLOCKED = {"911", "988", "211", "311", "411", "511", "611", "711", "811"}


class InvalidNumber(ValueError):
    """Raised when a number string cannot be normalised to a valid 11-digit NANP number."""


def normalize(s: str) -> str:
    """Strip non-digits, prepend '1' if 10 digits, and return the 11-digit string.

    Raises InvalidNumber if the result is not an 11-digit string starting with '1',
    or if the area code is one of the nine blocked codes.
    """
    d = re.sub(r"\D", "", s or "")
    if len(d) == 10:
        d = "1" + d
    if len(d) != 11 or not d.startswith("1"):
        raise InvalidNumber(f"number must be 10 or 11 digits (got {s!r})")
    if d[1:4] in _BLOCKED:
        raise InvalidNumber("refusing to fax an N11 number")
    return d
