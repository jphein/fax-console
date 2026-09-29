#!/usr/bin/env python3
"""Bobcoin budget gate and ledger for scripts/bob-run.sh (stdlib only; drift-gems, 2026-09-28).

The single ledger is docs/bob-usage.md: the table under "## Ledger" and the
"**Running total: ...**" line below it. This tool touches only those. The prose and the
"Kept / changed" reviews belong to people.

  status    USAGE.md                    print this billing cycle's spend against the caps
  reserve   USAGE.md --n N --slug S --max-cost C [--override "team-lead: why"]
  finalize  USAGE.md --n N --file RUN.jsonl --rc RC
  summarize RUN.jsonl                   the run's figures, as JSON

Budget: the account is Pro Plus, with 180 Bobcoins per billing cycle, renewing on the 28th, and
overage off.
* HARD_CAP (180, the allotment) and CYCLE_DAY (28) are constants. No flag or variable changes them.
* The soft cap is the one tunable (BOB_SOFT_CAP or --soft-cap, default 100). reserve refuses
  (exit 75) when the cycle's total + C would pass it without a lead override, and refuses under
  any override when the sum would pass HARD_CAP.
* Every cost and cap must be a finite number: a cap in [0, 180], a run's maximum in (0, 180], a
  ledger cost >= 0. Anything else is refused (exit 2). A cost Bob reports that is not a finite
  number >= 0 is an error that leaves the reservation counting (exit 3): never a credit.
* A run is reserved at C when it starts and replaced with Bob's measured `session_costs` when it
  ends. Both steps run under one lock per user and are also written to a per-user journal kept
  outside the repository, where Bob's sandbox cannot see it:
  ${XDG_STATE_HOME:-~/.local/state}/fax-console/bob-journal.jsonl. The cycle's total is the
  journal plus the ledger rows the journal does not know (runs from before it, IDE sessions), so
  two checkouts cannot each spend the full budget, and a ledger row that is deleted or edited
  down gives no cost back.
* finalize restores a row that went missing and exits 3, so a vanished row is loud.
"""

from __future__ import annotations

import argparse
import calendar
import contextlib
import fcntl
import json
import math
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

EX_CONFIG = 2          # a value the gate cannot trust: refused before anything runs
EX_LEDGER = 3          # finalize found a missing row or an invalid cost: recorded, and loud
EX_TEMPFAIL = 75       # a cap would be passed
HARD_CAP = 180.0       # the Pro Plus allotment; overage is off. A constant, on purpose.
CYCLE_DAY = 28         # the plan renews on the 28th. A constant, on purpose.
DEFAULT_SOFT_CAP = 100.0
HEADER_RX = re.compile(r"^\|\s*#\s*\|\s*Date\b")
TOTAL_RX = re.compile(r"\*\*Running total: [\d.]+ Bobcoins\*\* \(after run [^)]*\)\.")
OVERRIDE_RX = re.compile(r"^\s*(team-lead|lead|jp)\s*:\s*(?P<why>.{10,})$", re.IGNORECASE)
RUN_RX = re.compile(r"^[0-9]{1,6}$")
SLUG_RX = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")
LINK_RX = re.compile(r"bob-runs/(\d+)-([a-z0-9-]+)\.prompt\.md")


class BudgetError(Exception):
    """A value the gate cannot trust. It refuses rather than guesses."""


def finite(x, what: str, lo: float = 0.0, hi: float = math.inf, lo_open: bool = False) -> float:
    """x as a float in [lo, hi] (or (lo, hi]), or BudgetError. NaN, infinities and text fail."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise BudgetError(f"{what} must be a number, not {str(x)[:20]!r}") from None
    if not math.isfinite(v) or v < lo or (lo_open and v == lo) or v > hi:
        rng = f"{'(' if lo_open else '['}{lo:g}, {hi:g}]"
        raise BudgetError(f"{what} must be a finite number in {rng}, not {str(x)[:20]!r}")
    return v


# ---------------------------------------------------------------- the billing cycle
def _anchor(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def cycle_bounds(today: date, day: int = CYCLE_DAY) -> tuple[date, date]:
    """[start, end) of the billing cycle containing `today`, renewing on `day`."""
    this = _anchor(today.year, today.month, day)
    if today >= this:
        start = this
    else:
        y, m = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        start = _anchor(y, m, day)
    y, m = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return start, _anchor(y, m, day)


def row_date(cell: str, today: date) -> date | None:
    """The ledger writes 'M/D HH:MM' without a year: take the one nearest to today."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})", cell)
    if not m:
        return None
    mo, dd = int(m.group(1)), int(m.group(2))
    year = today.year - (mo - today.month > 6) + (today.month - mo > 6)
    try:
        return date(year, mo, dd)
    except ValueError:
        return None


# ---------------------------------------------------------------- the ledger table
def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def table_span(lines: list[str]) -> tuple[int, int]:
    """(index of the header, index just past the last row) of the Ledger table."""
    for i, line in enumerate(lines):
        if HEADER_RX.match(line):
            j = i + 2                                    # header, separator, then rows
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            return i, j
    raise BudgetError("no '| # | Date ...' ledger table in the usage file")


NO_COST = {"", "—", "–", "-", "0"}


def cost_of(cell: str) -> float:
    """A Cost cell: a figure, or a reservation "(x)" counted at x; an empty cell or a dash counts 0.
    Anything else that is not a finite number >= 0 is refused ("~3", "nan", "-5", a Unicode minus),
    because counting it as 0 would lower the total."""
    c = cell.strip().replace("\u2212", "-")
    if c.startswith("(") and c.endswith(")"):           # a reservation counts at its maximum
        c = c[1:-1].strip()
    if c in NO_COST:
        return 0.0
    try:
        v = float(c)
    except ValueError:
        raise BudgetError(f"a ledger Cost cell reads {cell.strip()[:20]!r}: "
                          "write a number, or — for none") from None
    if not math.isfinite(v) or v < 0:
        raise BudgetError(f"a ledger Cost cell reads {cell.strip()[:20]!r}: not a finite number >= 0")
    return v


def rows(lines: list[str]) -> list[list[str]]:
    h, end = table_span(lines)
    return [_cells(x) for x in lines[h + 2:end]]


def _write(path: Path, lines: list[str]) -> None:
    """Replace the file atomically: a kill mid-write leaves the old ledger, never an empty one."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".bob-usage.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, os.stat(path).st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------- the per-user journal
def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")) / "fax-console"


@contextlib.contextmanager
def locked():
    """One lock per user for every checkout: a separate file, so the ledger can be replaced."""
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "bob-budget.lock", "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def journal_append(rec: dict) -> None:
    p = state_dir() / "bob-journal.jsonl"
    torn = p.exists() and p.stat().st_size and not p.read_bytes().endswith(b"\n")
    with open(p, "a", encoding="utf-8") as f:
        f.write(("\n" if torn else "") + json.dumps(rec, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def journal_runs() -> dict:
    """{(checkout, n, slug): {"ts", "reserved", "cost"}} folded from the append-only journal. Only
    this tool writes it; a line it cannot read is a torn append and is skipped (loudly)."""
    runs: dict = {}
    p = state_dir() / "bob-journal.jsonl"
    if not p.exists():
        return runs
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        try:
            r = json.loads(line)
            key = (r["checkout"], str(r["n"]), r["slug"])
            if r["event"] == "reserve":
                reserved = finite(r["reserved"], f"journal line {i}", lo_open=True, hi=HARD_CAP)
                runs[key] = {"ts": r["ts"], "cost": None, "reserved": reserved}
            elif r["event"] == "final" and key in runs and r.get("cost") is not None:
                runs[key]["cost"] = finite(r["cost"], f"journal line {i}")
        except (ValueError, KeyError, TypeError, BudgetError) as e:
            print(f"bob-usage: journal line {i} skipped ({type(e).__name__})", file=sys.stderr)
    return runs


def checkout_of(path: Path) -> str:
    return str(path.resolve().parent.parent)


def cycle_total(lines: list[str], today: date, day: int = CYCLE_DAY, runs: dict | None = None) -> float:
    """This cycle's spend: the journal's runs, plus the ledger rows the journal does not know.
    A row the journal knows counts at the larger of the two figures."""
    start, end = cycle_bounds(today, day)
    by_run: dict = {}
    for (_co, n, slug), v in (runs or {}).items():
        if start <= date.fromisoformat(v["ts"][:10]) < end:
            figure = v["cost"] if v["cost"] is not None else v["reserved"]
            by_run[(n, slug)] = by_run.get((n, slug), 0.0) + figure
    total = sum(by_run.values())
    for r in rows(lines):
        d = row_date(r[1], today) if len(r) > 5 else None
        if d is None or not start <= d < end:
            continue
        c = cost_of(r[5])
        m = LINK_RX.search(r[2])
        key = (m.group(1), m.group(2)) if m and m.group(1) == r[0] else None
        total += max(0.0, c - by_run[key]) if key in by_run else c
    return total


# ---------------------------------------------------------------- the run's figures
def summarize(stream_lines) -> dict:
    result, errors, n_asst, n_tool, n_results = None, [], 0, 0, 0
    for raw in stream_lines:
        try:
            ev = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(ev, dict):
            continue
        t = ev.get("type")
        if t == "message" and str(ev.get("role", "")).lower() == "assistant":
            n_asst += 1
        elif t == "tool_use":
            n_tool += 1
        elif t == "error":
            errors.append(str(ev.get("message") or ev.get("error") or "error")[:120])
        elif t == "result":
            result = ev
            n_results += 1
    stats = (result or {}).get("stats") or {}
    raw_cost, cost, invalid = stats.get("session_costs"), None, False
    if raw_cost is not None or n_results > 1:
        try:
            # Bob prints one result. A second one is a forged or corrupt stream, whichever is first.
            if n_results > 1:
                raise BudgetError("more than one result event")
            if isinstance(raw_cost, bool) or not isinstance(raw_cost, (int, float)):
                raise BudgetError("session_costs must be a JSON number")
            cost = finite(raw_cost, "session_costs", hi=HARD_CAP)   # 1e308 would block every later run
        except BudgetError:
            invalid = True                       # never a credit: the reservation keeps counting
    tools = stats.get("tool_calls")
    return {"status": (result or {}).get("status") or ("error" if errors else "no-result"),
            "cost": cost, "cost_invalid": invalid,
            "tool_calls": tools if isinstance(tools, int) and not isinstance(tools, bool) else n_tool,
            "turns": n_asst, "task_id": stats.get("task_id"), "errors": errors}


# ---------------------------------------------------------------- commands
def status_line(lines, now: datetime, day: int, soft: float, hard: float, runs: dict | None = None) -> str:
    start, end = cycle_bounds(now.date(), day)
    spent = cycle_total(lines, now.date(), day, runs)
    return (f"bob budget: cycle {start:%b %d}–{end - timedelta(days=1):%b %d}: {spent:.3f} "
            f"Bobcoins logged; soft cap {soft:g} (lead override above), allotment {hard:g}, "
            f"{hard - spent:.1f} left")


def _title(slug: str) -> str:
    return slug.replace("-", " ").strip().capitalize() or "Run"


def reserve(path: Path, n: str, slug: str, max_cost, override: str | None, now: datetime,
            day: int = CYCLE_DAY, soft=DEFAULT_SOFT_CAP, hard: float = HARD_CAP) -> int:
    try:
        if not RUN_RX.match(n):
            raise BudgetError(f"the run number must be 1-6 digits, not {n[:20]!r}")
        if not SLUG_RX.match(slug):
            raise BudgetError(f"the slug must be lower-case letters, digits and '-', not {slug[:20]!r}")
        hard = finite(hard, "the allotment", lo_open=True)
        max_cost = finite(max_cost, "--max-cost", lo_open=True, hi=hard)
        soft = finite(soft, "the soft cap", hi=hard)
        with locked():
            lines = path.read_text(encoding="utf-8").splitlines()
            runs = journal_runs()
            me = (checkout_of(path), n, slug)
            if any(r[0] == n for r in rows(lines)) or me in runs:
                print(f"bob-usage: run {n} is already in the ledger or the journal", file=sys.stderr)
                return EX_CONFIG
            spent = cycle_total(lines, now.date(), day, runs)
            after = spent + max_cost
            if after > hard:
                print(f"bob-usage: REFUSED: {spent:.3f} this cycle + {max_cost:g} would pass the "
                      f"{hard:g}-Bobcoin allotment. No override lifts this.", file=sys.stderr)
                return EX_TEMPFAIL
            if after > soft and not OVERRIDE_RX.match(override or ""):
                print(f"bob-usage: REFUSED: {spent:.3f} this cycle + {max_cost:g} would pass the "
                      f"{soft:g}-Bobcoin cap. Rerun with BOB_OVERRIDE=\"team-lead: <reason>\".",
                      file=sys.stderr)
                return EX_TEMPFAIL
            journal_append({"event": "reserve", "ts": now.isoformat(timespec="seconds"), "checkout": me[0],
                            "n": n, "slug": slug, "reserved": max_cost,
                            "override": override.strip() if after > soft and override else None})
            note = "review pending" + (f"; override: {override.strip()}" if after > soft and override else "")
            row = (f"| {n} | {now:%-m/%-d %H:%M} | [{_title(slug)}](bob-runs/{n}-{slug}.prompt.md) | "
                   f"running | | ({max_cost:g}) | {note.replace('|', '/')} |")
            _, end = table_span(lines)
            lines.insert(end, row)
            _write(path, lines)
    except BudgetError as e:
        print(f"bob-usage: REFUSED: {e}", file=sys.stderr)
        return EX_CONFIG
    return 0


def finalize(path: Path, n: str, run_file: Path, rc: int, now: datetime | None = None,
             max_cost: float | None = None) -> dict:
    """Record the run's measured figures. The result carries `problems`: a restored row or an
    invalid cost. Either one makes the command exit 3.

    A cost is taken from the stream only when Bob exited 0. A killed or failed run can end with a
    result line that Bob never wrote (a process inside the sandbox can write to Bob's stdout and then
    kill it: the Oracle, 9/29), so it keeps counting at its reservation."""
    now = now or datetime.now().astimezone()
    s = summarize(run_file.read_text(encoding="utf-8", errors="replace").splitlines()
                  if run_file.exists() else [])
    if rc and s["cost"] is not None:
        s["cost"] = None                          # not trusted after a non-zero exit: the reservation counts
        s["cost_kept_reservation"] = True
    problems = []
    if s["cost_invalid"]:
        problems.append("Bob reported a cost that is not a finite number >= 0; the reservation still counts")
    out = s["status"] + (f" ({s['errors'][0]})" if s["errors"] else "") + (f", rc {rc}" if rc else "")
    out += "; invalid cost reported" if s["cost_invalid"] else ""
    with locked():
        lines = path.read_text(encoding="utf-8").splitlines()
        runs = journal_runs()
        mine = [k for k in runs if k[0] == checkout_of(path) and k[1] == n]
        h, end = table_span(lines)
        found = False
        for i in range(h + 2, end):
            c = _cells(lines[i])
            if c and c[0] == n and len(c) >= 7:
                found = True
                c[3] = out.replace("|", "/")
                c[4] = str(s["tool_calls"])
                if s["cost"] is not None:                 # unknown or invalid: the reservation counts
                    c[5] = f"{s['cost']:.3f}"
                lines[i] = "| " + " | ".join(c) + " |"
        if not found:
            problems.append(f"the ledger row for run {n} was missing; it is restored")
            key = mine[-1] if mine else None
            slug = key[2] if key else "unknown"
            reserved = runs[key]["reserved"] if key else None
            if reserved is None and max_cost is not None:
                reserved = finite(max_cost, "--max-cost", lo_open=True, hi=HARD_CAP)
            cost = (f"{s['cost']:.3f}" if s["cost"] is not None
                    else f"({reserved:g})" if reserved is not None else f"({HARD_CAP:g})")
            link = f"[{_title(slug)}](bob-runs/{n}-{slug}.prompt.md)"
            note = "restored by finalize: this row had gone missing"
            lines.insert(end, f"| {n} | {now:%-m/%-d %H:%M} | {link} | {out.replace('|', '/')} | "
                              f"{s['tool_calls']} | {cost} | {note} |")
        for key in mine[-1:]:
            journal_append({"event": "final", "ts": now.isoformat(timespec="seconds"), "checkout": key[0],
                            "n": n, "slug": key[2], "cost": s["cost"], "rc": rc})
        total = sum(cost_of(r[5]) for r in rows(lines) if len(r) > 5)
        lines = [TOTAL_RX.sub(f"**Running total: {total:.2f} Bobcoins** (after run {n}).", x)
                 for x in lines]
        _write(path, lines)
    s["problems"] = problems
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bobcoin budget gate and ledger")
    ap.add_argument("--soft-cap", help="the one tunable cap (default: BOB_SOFT_CAP, else 100)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status")
    st.add_argument("usage", type=Path)
    r = sub.add_parser("reserve")
    r.add_argument("usage", type=Path)
    r.add_argument("--n", required=True)
    r.add_argument("--slug", required=True)
    r.add_argument("--max-cost", required=True)
    r.add_argument("--override")
    fz = sub.add_parser("finalize")
    fz.add_argument("usage", type=Path)
    fz.add_argument("--n", required=True)
    fz.add_argument("--file", type=Path, required=True)
    fz.add_argument("--rc", type=int, required=True)
    fz.add_argument("--max-cost", help="the run's reservation, for a row the journal never saw")
    sm = sub.add_parser("summarize")
    sm.add_argument("file", type=Path)
    a = ap.parse_args(argv)
    for ignored in ("BOB_HARD_CAP", "BOB_CYCLE_DAY"):
        if os.environ.get(ignored):
            print(f"bob-usage: {ignored} is ignored: the allotment (180) and the cycle day (28) are "
                  "constants", file=sys.stderr)
    now = datetime.now().astimezone()     # the ledger is in local time (PDT)
    try:
        raw_soft = a.soft_cap if a.soft_cap is not None else os.environ.get("BOB_SOFT_CAP", DEFAULT_SOFT_CAP)
        soft = finite(raw_soft, "the soft cap (BOB_SOFT_CAP / --soft-cap)", hi=HARD_CAP)
        if a.cmd == "status":
            print(status_line(a.usage.read_text(encoding="utf-8").splitlines(), now, CYCLE_DAY,
                              soft, HARD_CAP, journal_runs()), file=sys.stderr)
            return 0
        if a.cmd == "reserve":
            return reserve(a.usage, a.n, a.slug, a.max_cost, a.override, now, CYCLE_DAY, soft, HARD_CAP)
        if a.cmd == "finalize":
            s = finalize(a.usage, a.n, a.file, a.rc, now, a.max_cost)
            print(json.dumps(s))
            for p in s["problems"]:
                print(f"bob-usage: finalize: {p}", file=sys.stderr)
            return EX_LEDGER if s["problems"] else 0
    except BudgetError as e:
        print(f"bob-usage: REFUSED: {e}", file=sys.stderr)
        return EX_CONFIG
    print(json.dumps(summarize(a.file.read_text(encoding="utf-8").splitlines())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
