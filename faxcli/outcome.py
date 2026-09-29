"""faxcli.outcome — judge a send from before/after fax show stats counters.

Pure function; no I/O.
"""


def judge(before: dict[str, int], after: dict[str, int]) -> dict:
    """Return a result dict with outcome (SENT/FAILED/UNKNOWN) and counter deltas.

    Mirrors the logic in legacy wait_for (cli.py:145–148).
    """
    completed_delta = after.get("Completed FAXes", 0) - before.get("Completed FAXes", 0)
    failed_delta = after.get("Failed FAXes", 0) - before.get("Failed FAXes", 0)
    if completed_delta > 0:
        outcome = "SENT"
    elif failed_delta > 0:
        outcome = "FAILED"
    else:
        outcome = "UNKNOWN"
    return {
        "outcome": outcome,
        "completed_delta": completed_delta,
        "failed_delta": failed_delta,
    }
