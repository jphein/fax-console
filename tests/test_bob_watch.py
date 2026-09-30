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
    ("=== 2025550142 passed in 0.1s ===", None),          # a phone-shaped count (Lucid, on #36)
    ("1 passed in 2025550142.5s", None),                  # a phone-shaped duration
    ("\uff13 failed in 1s", None),                         # fullwidth digits are not digits here
    ("99999 passed in 9999.99s", "99999 passed in 9999.99s"),   # the widest a real summary gets
    ("1 passed in 0.123s", None),                         # pytest prints two decimals
])
def test_the_summary_is_found(text, want):
    assert watch.test_summary(text) == want


def test_only_the_rebuilt_parts_are_shown():
    """Trailing text after the duration never reaches the screen."""
    line = watch.summary_line("2 passed in 0.1s  SECRETVALUE-do-not-show")
    assert "2 passed in 0.1s" in line and "SECRETVALUE" not in line


def test_the_key_is_masked_in_a_summary_too(monkeypatch):
    """summary_line goes through safe(), like everything else shown (Lucid, on #36). An all-digit key of 8
    or more digits cannot pass as a count at all, since a count has at most 5 digits."""
    monkeypatch.setattr(watch, "KEY", "1 passed")           # 8 characters, so safe() masks it
    assert watch.summary_line("1 passed in 1s").endswith("tests: *** in 1s" + watch.X)
    monkeypatch.setattr(watch, "KEY", "12345678")
    assert watch.summary_line("12345678 passed in 1s") is None


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
    assert "secret line one" not in shown                    # for an error too, since #38


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


LEAK = "leak-marker-7f3a"                                     # any text a command printed
ERR = "Error from tool execute_command: Exit code: {code}  Stdout: {out}  Stderr: {err}"


@pytest.mark.parametrize("msg, want", [
    (ERR.format(code=1, out="ok", err="error: Unable to create './.git/index.lock': Read-only file system"),
     "exit code 1 · read-only file system"),
    (ERR.format(code=1, out="Permission denied", err="boom"), "exit code 1"),       # stdout is not read
    (ERR.format(code=2, out="", err="bash: x: Permission denied"), "exit code 2 · permission denied"),
    (ERR.format(code=12345, out="", err=""), "failed"),              # not an exit code a shell gives
    ("write refused: the content carries identifying data (masked): <write>:1: [phone-number]",
     "the guard refused the write"),
    (ERR.format(code=1, out="E   path refused: outside", err=""), "exit code 1"),    # not at the start
    ("File does not exist: ./WORKLOG.md", "file does not exist"),
    ("something else entirely", "failed"),
])
def test_a_failed_tool_shows_fixed_words(msg, want):
    line = watch.error_line(msg)
    assert line == f"{watch.R}  ✗ {want} ({len(msg)} characters){watch.X}", line


@pytest.mark.parametrize("where", ["out", "err"])
def test_a_failed_tool_never_shows_its_message(where, capsys):
    """Another key or a home path in a failed command's output must not reach the screen (the Oracle,
    on #36)."""
    leak = f"{LEAK} /home/someone/.ssh/id_ed25519"
    msg = ERR.format(code=1, out=leak if where == "out" else "", err=leak if where == "err" else "")
    watch.render(json.dumps({"type": "tool_result", "status": "error", "error": {"message": msg}}), "")
    shown = capsys.readouterr().out
    assert LEAK not in shown and "/home/" not in shown and "exit code 1" in shown, shown


def test_every_recorded_failure_maps_to_fixed_words():
    """A regression net over the published recordings: each failed tool gets words from the lists, not the
    bare fallback, and run 5's git stash refusal reads as a read-only file system (the video's scene 4)."""
    lines = []
    for recording in sorted((ROOT / "docs" / "bob-runs").glob("*.jsonl")):
        if recording.name.endswith(".guard.jsonl"):
            continue
        for raw in recording.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if e.get("type") == "tool_result" and e.get("status") != "success":
                err = e.get("error")
                msg = err.get("message", err) if isinstance(err, dict) else err
                lines.append((recording.name, watch.error_line(msg)))
    assert len(lines) >= 39, len(lines)
    assert not [n for n, line in lines if "✗ failed (" in line], lines
    assert "✗ exit code 1 · read-only file system" in [line for n, line in lines if n.startswith("5-")][-1]
