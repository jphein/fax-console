"""The deck's "Bob from day one" slide is rebuilt from docs/bob-usage.md by docs/deck/timeline.py.

These tests keep that slide honest: every numbered run in the ledger reaches the slide, the day strip
covers the whole hackathon window, and a long ledger folds into weeks instead of running off the slide.
"""
import importlib.util
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("timeline", ROOT / "docs" / "deck" / "timeline.py")
timeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timeline)


def _run(n, month, day, task="A task", coins=1.0):
    return {"run": str(n), "month": str(month), "day": day, "task": task, "output": "", "coins": coins,
            "kept": ""}


def test_every_numbered_run_in_the_ledger_is_parsed_inside_the_window():
    runs = timeline.numbered(timeline.ledger_runs(timeline.LEDGER.read_text(encoding="utf-8")))
    assert runs, "no numbered runs parsed from docs/bob-usage.md"
    for r in runs:
        assert (int(r["month"]), r["day"]) >= (9, 28), r
        assert (int(r["month"]), r["day"]) <= (10, 18), r
        assert r["task"] and r["coins"] >= 0, r


def test_the_strip_has_one_cell_per_day_and_fills_only_days_with_runs():
    strip = timeline.strip_html([_run(0, 9, 28), _run(1, 9, 28), _run(2, 10, 18), _run("–", 9, 30)])
    assert strip.count('<span class="d') == 21                 # Sep 28 to Oct 18
    assert strip.count('class="d on"') == 2                     # the unnumbered setup row does not count
    assert 'title="Sep 28: 2 runs">2<' in strip and 'title="Oct 18: 1 run">1<' in strip


def test_days_stay_days_while_they_fit_then_fold_into_weeks():
    few = [_run(i, 9, 28 + i) for i in range(3)]
    assert [label for label, _ in timeline.groups(few)] == ["Sep 28", "Sep 29", "Sep 30"]
    days = [(9, 28), (9, 29), (9, 30), (10, 1), (10, 3), (10, 5), (10, 7), (10, 9), (10, 12), (10, 18)]
    many = [_run(i, m, d) for i, (m, d) in enumerate(days)]
    rows = timeline.groups(many)
    assert len(rows) <= timeline.MAX_ROWS
    assert [label.split(" · ")[0] for label, _ in rows] == ["Week 1", "Week 2", "Week 3"]
    assert sum(len(rs) for _, rs in rows) == len(many)          # folding never drops a run


def test_long_task_lists_are_cut_at_a_task_boundary():
    rs = [_run(i, 9, 28, task=f"Task {i} with a long descriptive name") for i in range(8)]
    text = timeline.tasks_text(rs, limit=110)
    assert len(text) < 150 and re.search(r" · and \d+ more$", text)
    assert text.split(" · ")[0] == "Task 0 with a long descriptive name"


def test_main_rewrites_only_between_the_markers_and_is_idempotent(tmp_path, monkeypatch):
    deck = tmp_path / "deck.html"
    deck.write_text("<p>before</p>\n<!-- strip:start -->STALE-PLACEHOLDER<!-- strip:end -->\n"
                    "<table><tbody>\n<!-- timeline:start -->\nSTALE-PLACEHOLDER\n<!-- timeline:end -->\n"
                    "</tbody></table>\n<p>after</p>\n", encoding="utf-8")
    monkeypatch.setattr(timeline, "DECK", deck)
    timeline.main()
    once = deck.read_text(encoding="utf-8")
    timeline.main()
    assert deck.read_text(encoding="utf-8") == once
    assert once.startswith("<p>before</p>") and once.endswith("<p>after</p>\n")
    assert "STALE-PLACEHOLDER" not in once
    assert '<tr class="total"><th scope="row">So far</th>' in once
