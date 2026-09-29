"""Bobcoin budget gate and ledger (scripts/bob_usage.py). No Bob, no network, no Bobcoins.

Every test gets its own per-user state directory (XDG_STATE_HOME), so the real journal in
~/.local/state is never read or written here.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bob_usage.py"
_spec = importlib.util.spec_from_file_location("bob_usage", SCRIPT)
bu = importlib.util.module_from_spec(_spec)
sys.modules["bob_usage"] = bu          # dataclasses/annotations resolve through sys.modules
_spec.loader.exec_module(bu)

LEDGER = """# How IBM Bob was used

## Ledger
Costs are Bob Shell's `session_costs`.

| # | Date (PDT) | Task | Bob's output | Tool calls | Cost | Kept / changed |
|---|---|---|---|---|---|---|
| – | 9/27 21:00 | Last cycle | one word | 0 | 50.000 | — |
| 0 | 9/28 22:13 | [Sandbox smoke](bob-runs/0-sandbox-smoke.prompt.md) | one file | 3 | 0.083 | kept |
| 1 | 9/28 22:15 | [Analysis](bob-runs/1-analysis.prompt.md) | analysis.md | 26 | 3.078 | kept |

**Running total: 53.16 Bobcoins** (after run 1).

## Run notes
Prose that the tool must never touch.
"""
PDT = timezone(timedelta(hours=-7))
NOW = datetime(2026, 9, 28, 23, 0, tzinfo=PDT)


@pytest.fixture(autouse=True)
def state(tmp_path: Path, monkeypatch) -> Path:
    s = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(s))
    for v in ("BOB_SOFT_CAP", "BOB_HARD_CAP", "BOB_CYCLE_DAY"):
        monkeypatch.delenv(v, raising=False)
    return s


def make_ledger(root: Path, text: str = LEDGER) -> Path:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    p = root / "docs" / "bob-usage.md"
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    return make_ledger(tmp_path / "checkout-a")


def reserve(p, n, cost, override=None, now=NOW, soft=100.0, slug="demo-run"):
    return bu.reserve(p, str(n), slug, cost, override, now, 28, soft, bu.HARD_CAP)


def run_file(tmp_path: Path, cost, name="run.jsonl") -> Path:
    f = tmp_path / name
    f.write_text("\n".join(json.dumps(e) for e in [
        {"type": "message", "role": "user", "content": "go"},
        {"type": "message", "role": "assistant", "content": "done"},
        {"type": "result", "status": "success",
         "stats": {"session_costs": cost, "tool_calls": 4, "task_id": "t-1", "max_cost": 5}}]))
    return f


def drop_row(p: Path, n: int) -> None:
    p.write_text("\n".join(x for x in p.read_text().splitlines() if not x.startswith(f"| {n} |")) + "\n")


def total(p: Path, now=NOW) -> float:
    return bu.cycle_total(p.read_text().splitlines(), now.date(), 28, bu.journal_runs())


# --- the billing cycle (renews on the 28th) --------------------------------------------------
@pytest.mark.parametrize("today,start,end", [
    (date(2026, 9, 28), date(2026, 9, 28), date(2026, 10, 28)),
    (date(2026, 9, 27), date(2026, 8, 28), date(2026, 9, 28)),
    (date(2026, 10, 27), date(2026, 9, 28), date(2026, 10, 28)),
    (date(2026, 10, 28), date(2026, 10, 28), date(2026, 11, 28)),
    (date(2027, 1, 5), date(2026, 12, 28), date(2027, 1, 28)),
])
def test_cycle_bounds(today, start, end):
    assert bu.cycle_bounds(today, 28) == (start, end)


def test_cycle_anchor_clamps_in_short_months():
    assert bu.cycle_bounds(date(2027, 3, 1), 31) == (date(2027, 2, 28), date(2027, 3, 31))


def test_row_dates_without_a_year_resolve_to_the_nearest_year():
    assert bu.row_date("12/30 10:00", date(2027, 1, 3)) == date(2026, 12, 30)
    assert bu.row_date("1/2 10:00", date(2026, 12, 30)) == date(2027, 1, 2)
    assert bu.row_date("—", date(2026, 9, 28)) is None


def test_cycle_total_excludes_the_previous_cycle(ledger):
    assert total(ledger) == pytest.approx(3.161)                          # not the 50 on 9/27


def test_the_allotment_and_the_cycle_day_are_constants():
    assert bu.HARD_CAP == 180 and bu.CYCLE_DAY == 28
    help_text = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True,
                               check=False).stdout
    assert "--hard-cap" not in help_text and "--cycle-day" not in help_text


# --- the gate --------------------------------------------------------------------------------
def test_reserve_then_finalize_updates_row_journal_and_running_total(ledger, tmp_path):
    assert reserve(ledger, 2, 5) == 0
    text = ledger.read_text()
    assert "| 2 | 9/28 23:00 | [Demo run](bob-runs/2-demo-run.prompt.md) | running | | (5) |" in text
    assert total(ledger) == pytest.approx(8.161)
    s = bu.finalize(ledger, "2", run_file(tmp_path, 1.5), 0, NOW)
    assert s == {"status": "success", "cost": 1.5, "cost_invalid": False, "tool_calls": 4, "turns": 1,
                 "task_id": "t-1", "errors": [], "problems": []}
    text = ledger.read_text()
    assert "| 2 | 9/28 23:00 | [Demo run](bob-runs/2-demo-run.prompt.md) | success | 4 | 1.500 |" in text
    assert "**Running total: 54.66 Bobcoins** (after run 2)." in text      # all rows, all time
    assert "Prose that the tool must never touch." in text
    assert total(ledger) == pytest.approx(4.661)
    events = [json.loads(x)["event"] for x in (bu.state_dir() / "bob-journal.jsonl").read_text().splitlines()]
    assert events == ["reserve", "final"]


def test_unknown_cost_keeps_counting_the_reservation(ledger, tmp_path):
    reserve(ledger, 2, 5)
    run = tmp_path / "2.jsonl"
    run.write_text("not json\n")
    s = bu.finalize(ledger, "2", run, 1, NOW)
    assert s["cost"] is None and s["problems"] == []
    assert total(ledger) == pytest.approx(8.161)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -150, "0.5", True])
def test_an_invalid_cost_from_bob_is_an_error_never_a_credit(ledger, tmp_path, bad):
    reserve(ledger, 2, 5)
    s = bu.finalize(ledger, "2", run_file(tmp_path, bad), 0, NOW)
    assert s["cost"] is None and s["cost_invalid"] and s["problems"]
    assert total(ledger) == pytest.approx(8.161)                          # still the full reservation
    assert "invalid cost reported" in ledger.read_text()


def test_default_soft_cap_is_100_and_needs_a_lead_override(ledger):
    assert reserve(ledger, 2, 90) == 0                                   # 3.161 + 90 <= 100
    assert reserve(ledger, 3, 10) == bu.EX_TEMPFAIL                      # would pass 100
    assert reserve(ledger, 3, 10, override="bob: pls") == bu.EX_TEMPFAIL
    assert reserve(ledger, 3, 10, override="team-lead: week-2 extraction, 23:05") == 0
    assert "override: team-lead: week-2 extraction" in ledger.read_text()


def test_hard_cap_180_holds_even_with_override(ledger):
    assert reserve(ledger, 2, 170, override="team-lead: one big refactor run") == 0     # 173.161
    assert reserve(ledger, 3, 7, override="jp: just one more please") == bu.EX_TEMPFAIL  # 180.161
    assert reserve(ledger, 3, 6.8, override="jp: just one more please") == 0            # 179.961


def test_hard_cap_boundary_is_exact(tmp_path):
    p = make_ledger(tmp_path / "c", LEDGER.replace("| 3.078 |", "| 0 |").replace("| 0.083 |", "| 0 |"))
    assert reserve(p, 2, 170, override="team-lead: boundary test run") == 0       # 170
    assert reserve(p, 3, 10.5, override="team-lead: boundary test run") == bu.EX_TEMPFAIL  # 180.5
    assert reserve(p, 3, 10, override="team-lead: boundary test run") == 0        # exactly 180
    assert reserve(p, 4, 0.001, override="team-lead: boundary test run") == bu.EX_TEMPFAIL


@pytest.mark.parametrize("cost", ["nan", "inf", "-1", "0", "181", "1e999", "three", None])
def test_a_max_cost_that_is_not_a_finite_positive_number_is_refused(ledger, cost):
    assert bu.reserve(ledger, "2", "demo-run", cost, None, NOW) == bu.EX_CONFIG
    assert "| 2 |" not in ledger.read_text()


@pytest.mark.parametrize("soft", ["nan", "inf", "-1", "181", "lots"])
def test_a_soft_cap_that_is_not_a_finite_number_in_range_is_refused(ledger, soft):
    assert bu.reserve(ledger, "2", "demo-run", 1, None, NOW, 28, soft) == bu.EX_CONFIG


@pytest.mark.parametrize("n,slug", [("2", "a|b|c"), ("2|x", "demo"), ("2", "Demo"), ("", "demo"),
                                    ("2", "-x"), ("1234567", "demo"), ("2", "a" * 61)])
def test_run_numbers_and_slugs_must_be_well_formed(ledger, n, slug):
    assert bu.reserve(ledger, n, slug, 1, None, NOW) == bu.EX_CONFIG
    assert total(ledger) == pytest.approx(3.161)


@pytest.mark.parametrize("cell", ["nan", "(nan)", "inf", "-150", "(-3)"])
def test_a_ledger_cost_that_would_lower_the_total_is_refused(tmp_path, cell):
    p = make_ledger(tmp_path / "c", LEDGER.replace("| 3.078 |", f"| {cell} |"))
    assert reserve(p, 2, 1) == bu.EX_CONFIG


def test_a_run_number_cannot_be_reused(ledger):
    assert reserve(ledger, 1, 1) == bu.EX_CONFIG


def test_a_missing_row_is_restored_and_reported(ledger, tmp_path):
    assert reserve(ledger, 2, 5) == 0
    drop_row(ledger, 2)                  # something (Bob, in a sandbox that failed) deletes the row
    s = bu.finalize(ledger, "2", run_file(tmp_path, 4.2), 0, NOW)
    assert s["problems"] and "missing" in s["problems"][0]
    restored = "| 2 | 9/28 23:00 | [Demo run](bob-runs/2-demo-run.prompt.md) | success | 4 | 4.200 |"
    assert restored in ledger.read_text()
    assert total(ledger) == pytest.approx(7.361)
    r = subprocess.run([sys.executable, str(SCRIPT), "finalize", str(ledger), "--n", "2",
                        "--file", str(run_file(tmp_path, 4.2)), "--rc", "0"], capture_output=True, text=True,
                       check=False)
    assert r.returncode == 0                                        # the row is back: nothing to report now


def test_a_row_deleted_before_the_next_reserve_still_counts(ledger, tmp_path):
    assert reserve(ledger, 2, 90) == 0
    bu.finalize(ledger, "2", run_file(tmp_path, 90.0), 0, NOW)
    drop_row(ledger, 2)
    assert reserve(ledger, 3, 10) == bu.EX_TEMPFAIL                # the journal still has the 90


def test_two_checkouts_share_one_budget(tmp_path):
    a = make_ledger(tmp_path / "checkout-a")
    b = make_ledger(tmp_path / "checkout-b")
    assert reserve(a, 2, 60) == 0
    bu.finalize(a, "2", run_file(tmp_path, 55.0), 0, NOW)
    assert reserve(b, 7, 50) == bu.EX_TEMPFAIL                     # 3.161 + 55 + 50 > 100
    assert reserve(b, 7, 40) == 0
    # once b merges a's row, it is not counted twice
    a_row = next(x for x in a.read_text().splitlines() if x.startswith("| 2 |"))
    b.write_text(b.read_text().replace("| 7 |", a_row + "\n| 7 |", 1))
    assert total(b) == pytest.approx(3.161 + 55 + 40)


def test_parallel_reserves_cannot_slip_past_a_cap_together(tmp_path):
    p = make_ledger(tmp_path / "c")                                 # 3.161 spent
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda i: subprocess.run(
            [sys.executable, str(SCRIPT), "reserve", str(p), "--n", str(10 + i), "--slug", "p",
             "--max-cost", "30"], capture_output=True, env={**os.environ}, check=False).returncode, range(8)))
    assert codes.count(0) == 3 and codes.count(bu.EX_TEMPFAIL) == 5     # 3.161 + 3 x 30 <= 100


def test_the_cli_ignores_attempts_to_raise_the_allotment(ledger, tmp_path):
    env = {**os.environ, "BOB_HARD_CAP": "1000", "BOB_CYCLE_DAY": "1"}
    r = subprocess.run([sys.executable, str(SCRIPT), "reserve", str(ledger), "--n", "2", "--slug", "big",
                        "--max-cost", "500", "--override", "team-lead: try to lift the cap"],
                       capture_output=True, text=True, env=env, check=False)
    assert r.returncode == bu.EX_CONFIG and "ignored" in r.stderr     # 500 > 180: refused outright
    r = subprocess.run([sys.executable, str(SCRIPT), "reserve", str(ledger), "--n", "2", "--slug", "big",
                        "--max-cost", "1", "--soft-cap", "nan"], capture_output=True, text=True,
                       check=False)
    assert r.returncode == bu.EX_CONFIG


def test_status_line_reports_the_cycle(ledger):
    line = bu.status_line(ledger.read_text().splitlines(), NOW, 28, 100, 180)
    assert line.startswith("bob budget: cycle Sep 28–Oct 27: 3.161 Bobcoins logged")
    assert "soft cap 100" in line and "allotment 180" in line


def test_the_ledger_is_replaced_atomically(ledger):
    before = ledger.stat().st_ino
    assert reserve(ledger, 2, 1) == 0
    assert ledger.stat().st_ino != before                          # a new file, renamed into place
    assert not list(ledger.parent.glob(".bob-usage.*"))            # no temp file left behind
