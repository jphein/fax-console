"""scripts/bob-watch.py: the terminal view of a Bob run, live or replayed from docs/bob-runs/.

It never shows what a tool printed, only its length, so a key in an env dump cannot land in scrollback.
The one exception is a pytest summary line, rebuilt from its counts, fixed words and duration: the
video's scene 4 shows tests going red, then green.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bob_watch", ROOT / "scripts" / "bob-watch.py")
watch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watch)


@pytest.mark.parametrize("text, want", [
    ("....\n3 failed, 186 passed in 1.98s\n", "3 failed, 186 passed in 1.98s"),
    ("===== 189 passed in 2.03s =====", "189 passed in 2.03s"),
    ("1 failed, 176 passed, 5 warnings in 2.08s", "1 failed, 176 passed, 5 warnings in 2.08s"),
    ("2 passed in 1s\nlater\n1 failed, 1 passed in 0.5s", "1 failed, 1 passed in 0.5s"),   # the last one
    ("no tests here", None),
    ("KEY=abc123 3 failed in 1s", None),                  # a summary must start the line
])
def test_the_summary_is_found(text, want):
    assert watch.test_summary(text) == want


def test_only_the_rebuilt_parts_are_shown():
    """Trailing text after the duration never reaches the screen."""
    line = watch.summary_line("2 passed in 0.1s  SECRETVALUE-do-not-show")
    assert "2 passed in 0.1s" in line and "SECRETVALUE" not in line


def test_red_when_anything_failed_green_otherwise():
    assert watch.summary_line("1 failed, 2 passed in 1s").startswith(watch.R)
    assert watch.summary_line("1 error in 1s").startswith(watch.R)
    assert watch.summary_line("3 passed in 1s").startswith(watch.G)


@pytest.mark.parametrize("status", ["success", "error"])
def test_a_tool_result_shows_its_summary_but_not_its_output(status, capsys):
    out = "secret line one\n=== 1 failed, 2 passed in 0.3s ===\n"
    e = {"type": "tool_result", "status": status}
    e.update({"output": out} if status == "success" else {"error": {"message": out}})
    watch.render(json.dumps(e), "")
    shown = capsys.readouterr().out
    assert "tests: 1 failed, 2 passed in 0.3s" in shown
    assert ("secret line one" not in shown) if status == "success" else True


def test_a_result_without_tests_shows_only_its_length(capsys):
    watch.render(json.dumps({"type": "tool_result", "status": "success", "output": "x" * 12}), "")
    shown = capsys.readouterr().out
    assert "12 characters of output" in shown and "tests:" not in shown


def test_run_5_replays_red_then_green():
    """The recording scene 4 films: its summaries go from failing to 189 passed."""
    shown = []
    recording = ROOT / "docs" / "bob-runs" / "5-faxcli-fixes.jsonl"
    for line in recording.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "tool_result":
            err = e.get("error")
            text = e.get("output", "") if e.get("status") == "success" else (
                err.get("message", "") if isinstance(err, dict) else err)
            s = watch.test_summary(text if isinstance(text, str) else json.dumps(text))
            if s:
                shown.append(s)
    assert any("failed" in s for s in shown) and shown[-1].startswith("189 passed"), shown
