"""scripts/bob-run.sh end to end, with a stub in place of the sandbox (drift-gems, 2026-09-29).

The real wrapper runs in a throwaway git repository in which exactly one file differs:
scripts/bob-sandbox.sh is a stub that prints a stream-json like Bob's and exits. So this starts
no Bob, uses no real key, reaches no network and spends no Bobcoins, and the invariant holds:
bob-run.sh starts Bob only through scripts/bob-sandbox.sh. tmux mode runs on a private tmux
server (its own socket directory), never on the workstation's.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KEY = "fake-" + "key-0123456789abcdef"                  # a stand-in; the real key is never read here
STUB = r"""#!/usr/bin/env bash
# A stand-in for scripts/bob-sandbox.sh in tests: never Bob, never the network.
touch "$STUB_MARK"
case "${STUB_MODE:-ok}" in
  ok)     cost=0.25; st=success; code=0 ;;
  fail)   cost=0.5;  st=error;   code=3 ;;
  nan)    cost=NaN;  st=success; code=0 ;;
  tamper) cost=0.25; st=success; code=0      # as if the sandbox let Bob edit the ledger
          grep -v '^| [0-9]* | .*review pending' docs/bob-usage.md > docs/.t
          cat docs/.t > docs/bob-usage.md; rm docs/.t ;;
  rename) cost=0.001; st=success; code=0     # as if Bob renamed docs/ and planted its own
          mv docs docs.old && mkdir -p docs/bob-runs && printf 'forged\n' > docs/bob-usage.md ;;
  twice)  cost=0.001; st=success; code=0     # a second, forged result line in the stream
          printf '{"type":"result","status":"success","stats":{"session_costs":0.001}}\n' ;;
  glued)  cost=2.5; st=success; code=0 ;;     # see the result line below
  killed) printf '{"type":"result","status":"success","stats":{"session_costs":0.001}}\n'
          exit 137 ;;                         # a forged result, then Bob killed: one result, not Bob's
esac
printf '%s\n' '{"type":"message","role":"assistant","content":"working\n"}'
printf '%s\n' '{"type":"tool_use","tool_name":"execute_command","parameters":{"command":"env"}}'
printf '{"type":"tool_result","status":"success","output":"BOB_API_KEY=%s"}\n' "$BOB_API_KEY"
refused='{"type":"tool_result","status":"error","error":{"message":"refused: write to %s/Projects/other/x"}}'
printf "$refused\n" "$HOME"
stats='"tool_calls":1,"task_id":"t-stub","max_cost":3'
if [ "${STUB_MODE:-}" = glued ]; then   # a fake result, then a fragment that swallows the real result line
  printf '{"type":"result","status":"success","stats":{"session_costs":0.001}}\n{"x":"'
fi
printf '{"type":"result","status":"%s","stats":{"session_costs":%s,%s}}\n' "$st" "$cost" "$stats"
exit "$code"
"""


def ledger(spent: str) -> str:
    today = datetime.now().astimezone().strftime("%-m/%-d %H:%M")      # inside the current cycle
    return (f"# How IBM Bob was used\n\n## Ledger\n"
            "| # | Date (PDT) | Task | Bob's output | Tool calls | Cost | Kept / changed |\n"
            "|---|---|---|---|---|---|---|\n"
            f"| – | {today} | Earlier work | — | 0 | {spent} | — |\n\n"
            f"**Running total: {spent} Bobcoins** (after run 0).\n")


@pytest.fixture
def box(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "docs" / "bob-runs").mkdir(parents=True)
    (repo / ".bob").mkdir()
    for f in ("bob-run.sh", "bob_usage.py", "bob-watch.py", "scrub-check.sh"):
        shutil.copy2(ROOT / "scripts" / f, repo / "scripts" / f)
    stub = repo / "scripts" / "bob-sandbox.sh"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)
    (repo / "docs" / "bob-usage.md").write_text(ledger("1.000"), encoding="utf-8")
    for n in (5, 6, 7):
        (repo / "docs" / "bob-runs" / f"{n}-demo.prompt.md").write_text("Reply with the word ok.\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    envf = tmp_path / "bob-env"
    envf.write_text(f"export BOB_API_KEY={KEY}\n", encoding="utf-8")
    envf.chmod(0o600)
    deny = tmp_path / "deny.txt"
    deny.write_text("zz-no-real-value-zz\n", encoding="utf-8")
    (tmp_path / "home").mkdir()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("TMUX", "BOB_")) and k != "XDG_STATE_HOME"}
    env.update(HOME=str(tmp_path / "home"), BOB_ENV=str(envf), XDG_STATE_HOME=str(tmp_path / "state"),
               FAX_CONSOLE_SCRUB_DENY=str(deny), STUB_MARK=str(tmp_path / "stub-ran"))
    return repo, env, tmp_path


def run(box, *args, **extra):
    repo, env, _ = box
    return subprocess.run(["bash", "scripts/bob-run.sh", *args], cwd=repo, env={**env, **extra},
                          capture_output=True, text=True, timeout=180, check=False)


def row(box, n):
    text = (box[0] / "docs" / "bob-usage.md").read_text(encoding="utf-8")
    return next((x for x in text.splitlines() if x.startswith(f"| {n} |")), None)


def stub_ran(box):
    return (box[2] / "stub-ran").exists()


def test_a_run_records_its_measured_cost_and_never_the_key(box):
    r = run(box, "5", "demo", "3")
    assert r.returncode == 0, r.stderr
    assert "| success | 1 | 0.250 |" in row(box, 5)
    assert r.stderr.count("bob budget:") == 2                         # before and after the run
    assert "run cost: 0.25" in r.stdout and "characters of output" in r.stdout
    runs = box[0] / "docs" / "bob-runs"
    recording = (runs / "5-demo.jsonl").read_text()
    assert "BOB_API_KEY=***" in recording
    assert "~/Projects/other/x" in recording and str(box[2] / "home") not in recording   # no home path
    for text in (r.stdout, r.stderr, (runs / "5-demo.jsonl").read_text(),
                 (runs / "5-demo.guard.jsonl").read_text(), (box[0] / "docs" / "bob-usage.md").read_text()):
        assert KEY not in text


def test_a_run_past_the_soft_cap_needs_a_lead_override(box):
    (box[0] / "docs" / "bob-usage.md").write_text(ledger("98.500"), encoding="utf-8")
    r = run(box, "5", "demo", "3")
    assert r.returncode == 75 and not stub_ran(box) and row(box, 5) is None
    r = run(box, "5", "demo", "3", BOB_OVERRIDE="team-lead: end-to-end override test")
    assert r.returncode == 0 and stub_ran(box)


@pytest.mark.parametrize("args", [
    ("5", "demo", "nan"), ("5", "demo", "inf"), ("5", "demo", "-1"), ("5", "demo", "0"),
    ("5", "demo", "1e3"), ("5", "demo", "181"), ("5", "demo", "3;x"), ("5", "a|b", "3"),
    ("5x", "demo", "3"), ("5", "Demo", "3"),
], ids=lambda a: "-".join(a))
def test_malformed_input_is_refused_before_anything_runs(box, args):
    before = (box[0] / "docs" / "bob-usage.md").read_text()
    r = run(box, *args)
    assert r.returncode == 2 and not stub_ran(box)
    assert (box[0] / "docs" / "bob-usage.md").read_text() == before


def test_a_soft_cap_that_is_not_a_number_is_refused(box):
    r = run(box, "5", "demo", "3", BOB_SOFT_CAP="nan")
    assert r.returncode == 2 and not stub_ran(box)


def test_the_allotment_cannot_be_raised_from_the_environment(box):
    (box[0] / "docs" / "bob-usage.md").write_text(ledger("178.000"), encoding="utf-8")
    r = run(box, "5", "demo", "3", BOB_HARD_CAP="1000", BOB_OVERRIDE="team-lead: try to pass the allotment")
    assert r.returncode == 75 and not stub_ran(box) and "ignored" in r.stderr


def test_a_failed_run_keeps_its_row_its_exit_code_and_its_reservation(box):
    r = run(box, "5", "demo", "3", STUB_MODE="fail")
    assert r.returncode == 3
    assert "error, rc 3" in row(box, 5) and "| (3) |" in row(box, 5)     # a non-zero exit: not trusted


def test_a_forged_result_before_a_kill_is_not_a_credit(box):
    r = run(box, "5", "demo", "3", STUB_MODE="killed")
    assert r.returncode == 137 and "| (3) |" in row(box, 5)
    assert (box[0] / "docs" / "bob-runs" / "5-demo.guard.jsonl").exists()


def test_a_nan_cost_is_an_error_not_a_credit(box):
    r = run(box, "5", "demo", "3", STUB_MODE="nan")
    assert r.returncode == 3
    assert "| (3) |" in row(box, 5) and "invalid cost reported" in row(box, 5)


def test_a_replaced_docs_dir_is_refused_and_nothing_is_touched(box):
    r = run(box, "5", "demo", "3", STUB_MODE="rename")
    assert r.returncode == 3 and "NOT recorded" in r.stderr
    real = box[0] / "docs.old"
    reserved = next(x for x in (real / "bob-usage.md").read_text().splitlines() if x.startswith("| 5 |"))
    assert "| (3) |" in reserved
    assert not (real / "bob-runs" / "5-demo.jsonl").exists()                 # nothing copied anywhere
    assert (box[0] / "docs" / "bob-usage.md").read_text() == "forged\n"      # the fake is left as found
    kept = list((box[2] / "state" / "fax-console" / "runs").glob("*-5-demo.jsonl"))
    assert len(kept) == 1 and oct(kept[0].stat().st_mode & 0o777) == "0o600"   # the stream, kept private


def test_a_second_result_line_is_an_error_not_a_credit(box):
    r = run(box, "5", "demo", "3", STUB_MODE="twice")
    assert r.returncode == 3 and "| (3) |" in row(box, 5) and "invalid cost reported" in row(box, 5)


def test_a_result_glued_onto_a_fragment_is_not_a_credit(box):
    r = run(box, "5", "demo", "3", STUB_MODE="glued")                    # Bob itself exits 0
    assert r.returncode == 3 and "| (3) |" in row(box, 5) and "invalid cost reported" in row(box, 5)


def test_the_private_recording_is_removed_once_published(box):
    assert run(box, "5", "demo", "3").returncode == 0
    assert not list((box[2] / "state" / "fax-console" / "runs").glob("*.jsonl"))


def test_a_deleted_row_is_restored_and_the_run_exits_3(box):
    r = run(box, "5", "demo", "3", STUB_MODE="tamper")
    assert r.returncode == 3 and "had gone missing" in row(box, 5) and "| 0.250 |" in row(box, 5)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="needs tmux")
def test_tmux_mode_keeps_every_window_and_matches_the_session_exactly(box):
    sock = tempfile.mkdtemp(prefix="bt", dir="/tmp")    # a socket path must stay short (108 bytes)
    env = {**box[1], "TMUX_TMPDIR": sock}
    tmux = ["tmux"]
    try:
        subprocess.run([*tmux, "new-session", "-d", "-s", "bobtest-long"], env=env, check=True)
        for n in (5, 6, 7):                               # runs that end at once: no exit may race
            r = run(box, str(n), "demo", "3", TMUX_TMPDIR=sock, BOB_TMUX="1",
                    BOB_TMUX_SESSION="bobtest", BOB_WAIT_TIMEOUT="120")
            assert r.returncode == 0, r.stderr
            assert "| success | 1 | 0.250 |" in row(box, n)
        wins = subprocess.run([*tmux, "list-windows", "-t", "=bobtest", "-F", "#{window_name} #{pane_dead}"],
                              env=env, capture_output=True, text=True, check=True).stdout.split("\n")
        assert {"run-5 1", "run-6 1", "run-7 1"} <= set(wins)       # kept open after the run ended
        long_wins = subprocess.run([*tmux, "list-windows", "-t", "=bobtest-long", "-F", "#{window_name}"],
                                   env=env, capture_output=True, text=True, check=True).stdout.split()
        assert not any(w.startswith("run-") for w in long_wins)     # not matched by prefix
        assert not list((box[0] / "docs" / "bob-runs").glob(".run-*"))
    finally:
        subprocess.run([*tmux, "kill-server"], env=env, capture_output=True, check=False)
        shutil.rmtree(sock, ignore_errors=True)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="needs tmux")
def test_tmux_mode_does_not_inherit_the_servers_variables(box):
    # The tmux server was started with a journal location the caller does not have: the run must
    # use the caller's (here, the default under its HOME), not the server's.
    sock = tempfile.mkdtemp(prefix="bt", dir="/tmp")
    elsewhere = box[2] / "elsewhere"
    env = {k: v for k, v in box[1].items() if k != "XDG_STATE_HOME"}
    try:
        subprocess.run(["tmux", "new-session", "-d", "-s", "bobtest"], check=True,
                       env={**env, "TMUX_TMPDIR": sock, "XDG_STATE_HOME": str(elsewhere)})
        r = subprocess.run(["bash", "scripts/bob-run.sh", "5", "demo", "3"], cwd=box[0], capture_output=True,
                           text=True, timeout=180, check=False,
                           env={**env, "TMUX_TMPDIR": sock, "BOB_TMUX": "1", "BOB_TMUX_SESSION": "bobtest"})
        assert r.returncode == 0, r.stderr
        assert (box[2] / "home" / ".local" / "state" / "fax-console" / "bob-journal.jsonl").exists()
        assert not elsewhere.exists()
    finally:
        subprocess.run(["tmux", "kill-server"], env={**env, "TMUX_TMPDIR": sock}, capture_output=True,
                       check=False)
        shutil.rmtree(sock, ignore_errors=True)
