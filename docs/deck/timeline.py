#!/usr/bin/env python3
"""Rebuild the deck's "Bob from day one" timeline from the ledger in docs/bob-usage.md.

    python3 docs/deck/timeline.py      # rewrites the rows between the timeline markers in docs/deck/deck.html

The ledger is the source of truth: one row per Bob run, with its date, task, output, cost and what
was kept or changed. This groups the runs by day, so the slide shows Bob in the work from the first
evening of the hackathon onward. Run it before every deck render.
"""
import datetime as dt
import html
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs" / "bob-usage.md"
DECK = ROOT / "docs" / "deck" / "deck.html"
START, END = "<!-- timeline:start -->", "<!-- timeline:end -->"
MONTHS = {"9": "Sep", "10": "Oct"}


def plain(cell):
    cell = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cell)    # [text](link) -> text
    cell = re.sub(r"[`*]", "", cell)
    return cell.strip()


def ledger_runs(text):
    runs, in_table = [], False
    for line in text.splitlines():
        if line.startswith("| # | Date"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 7 or set(cells[0]) <= {"-", ":"}:
                continue
            num, date, task, output, _calls, cost, kept = cells[:7]
            m = re.match(r"(\d{1,2})/(\d{1,2})", date)
            if not m:
                continue
            try:
                coins = float(cost)
            except ValueError:
                coins = 0.0
            runs.append({"run": plain(num), "month": m.group(1), "day": int(m.group(2)),
                         "task": plain(task), "output": plain(output), "coins": coins, "kept": plain(kept)})
    return runs


def numbered(runs):
    return [r for r in runs if r["run"] not in ("–", "-", "")]


def by_day(runs):
    days = {}
    for r in runs:
        days.setdefault((int(r["month"]), r["day"]), []).append(r)
    return [days[k] for k in sorted(days)]


MAX_ROWS = 8       # the slide holds about eight rows; past that the table folds into hackathon weeks
FIRST_DAY = (9, 28)


def day_label(r):
    return f'{MONTHS.get(r["month"], r["month"])} {r["day"]}'


def groups(runs):
    """(label, runs) per day while the days fit on the slide, else per hackathon week.
    The day strip above the table always stays day by day."""
    days = by_day(runs)
    if len(days) <= MAX_ROWS:
        return [(day_label(d[0]), d) for d in days]
    start, weeks = dt.date(2026, *FIRST_DAY), {}
    for d in days:
        n = (dt.date(2026, int(d[0]["month"]), d[0]["day"]) - start).days // 7 + 1
        weeks.setdefault(n, []).append(d)
    out = []
    for n in sorted(weeks):
        first, last = weeks[n][0][0], weeks[n][-1][0]
        span = day_label(first) if first is last else f"{day_label(first)} to {day_label(last)}"
        out.append((f"Week {n} · {span}", [r for d in weeks[n] for r in d]))
    return out


def tasks_text(rs, limit=110):
    names, used = [], 0
    for r in rs:
        if names and used + len(r["task"]) > limit:
            return " · ".join(names) + f" · and {len(rs) - len(names)} more"
        names.append(r["task"])
        used += len(r["task"]) + 3
    return " · ".join(names)


def row_html(label, rs, limit=110):
    nums = numbered(rs)
    coins = sum(r["coins"] for r in rs)
    tasks = html.escape(tasks_text(nums or rs[:1], limit))
    runs = f'runs {nums[0]["run"]} to {nums[-1]["run"]}' if len(nums) > 1 else (
        f'run {nums[0]["run"]}' if nums else "setup")
    return (f'<tr><th scope="row">{html.escape(label)}</th><td class="runs">{html.escape(runs)}</td>'
            f'<td>{tasks}</td><td class="coins">{coins:.2f}</td></tr>')


STRIP_START, STRIP_END = "<!-- strip:start -->", "<!-- strip:end -->"


def strip_html(runs):
    """One cell per day of the hackathon window, filled on days Bob ran."""
    counts = {}
    for r in runs:
        if r in numbered([r]):
            counts[(int(r["month"]), r["day"])] = counts.get((int(r["month"]), r["day"]), 0) + 1
    day, last, cells = dt.date(2026, 9, 28), dt.date(2026, 10, 18), []
    while day <= last:
        n = counts.get((day.month, day.day), 0)
        tip = f'{MONTHS[str(day.month)]} {day.day}: {n} run{"s" if n != 1 else ""}'
        cells.append(f'<span class="d{" on" if n else ""}" title="{tip}">{n if n else ""}</span>')
        day += dt.timedelta(days=1)
    return "".join(cells)


def main():
    runs = ledger_runs(LEDGER.read_text(encoding="utf-8"))
    g = groups(runs)
    limit = max(110, 440 // len(g))   # fewer rows leave room for more task names per row
    rows = "\n".join(row_html(label, rs, limit) for label, rs in g)
    total = sum(r["coins"] for r in runs)
    body = (f'{rows}\n<tr class="total"><th scope="row">So far</th>'
            f'<td class="runs">{len(numbered(runs))} runs</td><td>on {len(by_day(runs))} of the 21 days</td>'
            f'<td class="coins">{total:.2f}</td></tr>')
    deck = DECK.read_text(encoding="utf-8")
    a, b = deck.index(START) + len(START), deck.index(END)
    deck = deck[:a] + "\n" + body + "\n" + deck[b:]
    a, b = deck.index(STRIP_START) + len(STRIP_START), deck.index(STRIP_END)
    DECK.write_text(deck[:a] + strip_html(runs) + deck[b:], encoding="utf-8")
    print(f"timeline: {len(runs)} ledger rows, {len(by_day(runs))} day(s), {len(g)} table row(s), "
          f"{total:.2f} Bobcoins")


if __name__ == "__main__":
    main()
