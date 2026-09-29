"""faxcli.outcome — judge a send from before/after fax show stats counters.

Pure function; no I/O.
"""


def judge(
    before: dict[str, int],
    after: dict[str, int],
    *,
    before_ok: bool = True,
    after_ok: bool = True,
) -> dict:
    """Return a result dict with outcome (SENT/FAILED/UNKNOWN/UNMEASURED) and counter deltas.

    Mirrors the logic in legacy wait_for (cli.py:145–148), with one deliberate
    change: if *before_ok* or *after_ok* is False the stats read failed, so
    any delta would be measured from zero rather than the true baseline.
    In that case the outcome is "UNMEASURED" and both deltas are None.
    """
    if not before_ok or not after_ok:
        return {
            "outcome": "UNMEASURED",
            "completed_delta": None,
            "failed_delta": None,
        }
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
