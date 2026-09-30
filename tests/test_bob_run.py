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
# Bob's own log, saved where the caller named it, as the real sandbox does (STUB_LOCK: ok, nopolicy,
# offorigin, nolog); scripts/bob_lock_check.py reads it after the run
if [ "${STUB_LOCK:-ok}" != nolog ] && [ -n "${FAX_CONSOLE_BOB_LOG_DIR:-}" ]; then
  mkdir -p "$FAX_CONSOLE_BOB_LOG_DIR/shell"; lg="$FAX_CONSOLE_BOB_LOG_DIR/shell/bob-shell-t.log"; : > "$lg"
  [ "${STUB_LOCK:-ok}" = nopolicy ] ||
    printf '%s\n' '{"module":"PolicyService","msg":"Loaded 1 policy/policies from file: GatewayUrl"}' >> "$lg"
  gw=https://api.us-east.bob.ibm.com; [ "${STUB_LOCK:-ok}" = offorigin ] && gw=https://attacker.example
  req='{"module":"Gateway","msg":"HTTP request","data":{"url":"%s/inference/v1/chat/completions"}}'
  printf "$req\n" "$gw" >> "$lg"
fi
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
  plant)  cost=0.25; st=success; code=0      # modules left at the repo root for the host's Python
          for m in json re subprocess hashlib; do
            printf 'open(%s, "a").write("%s")\n' "'$STUB_MARK.pwned'" "$m" > "$m.py"
          done ;;
  killed) printf '{"type":"result","status":"success","stats":{"session_costs":0.001}}\n'
          exit 137 ;;                         # a forged result, then Bob killed: one result, not Bob's
  refused) cost=0.25; st=success; code=0     # a write the sandbox guard refused (aurora-bob, 9/29)
          u='{"type":"tool_use","tool_id":"w1","tool_name":"write_file",'
          printf '%s%s\n' "$u" '"parameters":{"path":"x.md","content":"refused-content-marker"}}'
          e='{"type":"tool_result","tool_id":"w1","status":"error",'
          printf '%s%s\n' "$e" '"error":"write refused: the content carries identifying data (masked)"}' ;;
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
    for f in ("bob-run.sh", "bob_usage.py", "bob-watch.py", "scrub-check.sh", "redact-refused.py",
              "bob_lock_check.py"):
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


def test_every_run_checks_the_gateway_lock_in_its_own_bob_log(box):
    r = run(box, "5", "demo", "3")
    assert r.returncode == 0 and "bob-lock: OK" in r.stdout, r.stdout + r.stderr
    logs = box[2] / "state" / "fax-console" / "bob-logs"
    saved = [d.name for d in logs.iterdir()]
    assert len(saved) == 1 and saved[0].endswith("-5-demo")          # this run's own directory
    assert "/inference" not in r.stdout                               # origins only


@pytest.mark.parametrize("lock", ["nopolicy", "offorigin", "nolog"])
def test_a_run_whose_log_does_not_show_the_lock_fails_and_keeps_its_reservation(box, lock):
    r = run(box, "5", "demo", "3", STUB_LOCK=lock)
    assert r.returncode == 4 and "FAILED the gateway-lock check" in r.stderr, r.stdout + r.stderr
    assert "rc 4" in row(box, 5) and "| (3) |" in row(box, 5)       # the reported 0.25 is not trusted
    assert (box[0] / "docs" / "bob-runs" / "5-demo.jsonl").exists()   # the transcript is still published


def test_a_failed_run_keeps_its_own_exit_code_when_the_lock_check_also_fails(box):
    r = run(box, "5", "demo", "3", STUB_MODE="fail", STUB_LOCK="nopolicy")
    assert r.returncode == 3 and "FAILED the gateway-lock check" in r.stderr


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


def test_modules_bob_leaves_at_the_repo_root_never_run_on_the_host(box):
    r = run(box, "5", "demo", "3", STUB_MODE="plant")
    assert r.returncode == 0, r.stderr
    assert "| success | 1 | 0.250 |" in row(box, 5)              # every host-side step still worked
    assert not (box[2] / "stub-ran.pwned").exists()               # and none of them imported the plants


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


def test_a_write_the_guard_refused_is_published_without_its_content(box):
    """scripts/redact-refused.py runs on the published copy, after the relativize-and-redact step and
    before the scrub: the content of a refused write is exactly what the guard keeps out."""
    r = run(box, "5", "demo", "3", STUB_MODE="refused")
    assert r.returncode == 0, r.stderr
    recording = (box[0] / "docs" / "bob-runs" / "5-demo.jsonl").read_text()
    assert "refused-content-marker" not in recording
    assert "<not published: the sandbox guard refused this write>" in recording
    assert "| success | 1 | 0.250 |" in row(box, 5)          # the cost comes from the private copy


@pytest.mark.parametrize("where", ["outside", "nested", "dotdot", "dot", "taken", "bare"])
def test_the_real_sandbox_refuses_a_bad_log_directory_before_touching_anything(tmp_path, where):
    """scripts/bob-sandbox.sh itself (not the stub), in a throwaway repository: a log directory
    outside bob-logs/, nested, relative-looking or already used is refused, and nothing is made."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "bob-sandbox.sh", repo / "scripts" / "bob-sandbox.sh")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    logs = tmp_path / "state" / "fax-console" / "bob-logs"
    (logs / "taken").mkdir(parents=True)
    target = {"outside": str(tmp_path / "elsewhere"), "nested": f"{logs}/a/b", "dotdot": f"{logs}/../x",
              "dot": f"{logs}/.", "taken": f"{logs}/taken", "bare": f"{logs}/"}[where]
    env = {k: v for k, v in os.environ.items() if not k.startswith("BOB_")}
    env.update(XDG_STATE_HOME=str(tmp_path / "state"), HOME=str(tmp_path), FAX_CONSOLE_BOB_LOG_DIR=target)
    r = subprocess.run(["bash", "scripts/bob-sandbox.sh", "true"], cwd=repo, env=env, capture_output=True,
                       text=True, timeout=60, check=False)
    assert r.returncode == 2 and "refusing:" in r.stderr, r.stderr
    assert not (repo / ".bob").exists()                                 # refused before anything was made
    assert sorted(p.name for p in logs.iterdir()) == ["taken"]


@pytest.mark.parametrize("rel,target", [
    ("scratch", ".."), ("docs/deck", "../.."), ("docs", ".."), (".venv", ".."),
    (".bob/guard.log", "../../x"), (".bob/tmp", "../.."),
])
def test_the_real_sandbox_refuses_a_symlinked_bind_path(tmp_path, rel, target):
    """bubblewrap follows a symlink at a bind path: `scratch -> ..` showed Bob the directory above the repo
    (the Oracle, PR #10). The real scripts/bob-sandbox.sh must refuse such a tree before making anything."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "bob-sandbox.sh", repo / "scripts" / "bob-sandbox.sh")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).symlink_to(target)
    env = {k: v for k, v in os.environ.items() if not k.startswith("BOB_")}
    env.update(XDG_STATE_HOME=str(tmp_path / "state"), HOME=str(tmp_path))
    r = subprocess.run(["bash", "scripts/bob-sandbox.sh", "true"], cwd=repo, env=env, capture_output=True,
                       text=True, timeout=60, check=False)
    assert r.returncode == 2 and "is a symlink" in r.stderr, r.stderr
    assert not (repo / ".bob" / "tmp").is_dir() or rel == ".bob/tmp"    # refused before anything was made
    assert not (tmp_path / "x").exists()                                # nothing touched through the link


def test_the_sandbox_mounts_scratch_as_an_empty_tmpfs_and_binds_no_symlink(tmp_path):
    """The real scripts/bob-sandbox.sh, with a fake sudo first on PATH that records the bwrap argv (the
    Oracle's CI recipe). scratch/ must be an empty read-only tmpfs, never a bind of the host's scratch/, and
    no --bind/--ro-bind source under the repo may be a symlink."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "bob-sandbox.sh", repo / "scripts" / "bob-sandbox.sh")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    fake = tmp_path / "bin"
    fake.mkdir()
    argv = tmp_path / "argv"
    (fake / "sudo").write_text(f"#!/bin/sh\nfor a in \"$@\"; do printf '%s\\n' \"$a\"; done > {argv}\n",
                               encoding="utf-8")
    (fake / "sudo").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("BOB_")}
    env.update(XDG_STATE_HOME=str(tmp_path / "state"), HOME=str(tmp_path), PATH=f"{fake}:{env['PATH']}")
    r = subprocess.run(["bash", "scripts/bob-sandbox.sh", "true"], cwd=repo, env=env, capture_output=True,
                       text=True, timeout=60, check=False)
    assert r.returncode == 0 and argv.exists(), r.stderr
    a = argv.read_text(encoding="utf-8").splitlines()
    root = str(repo.resolve())
    at = [j for j, x in enumerate(a) if x == "--tmpfs" and a[j + 1] == f"{root}/scratch"]
    assert len(at) == 1 and a[at[0] + 2:at[0] + 4] == ["--remount-ro", f"{root}/scratch"], a
    binds = [a[j + 1] for j, x in enumerate(a) if x in ("--bind", "--ro-bind")]
    assert f"{root}/scratch" not in binds                              # never the host's scratch/
    assert all(not Path(s).is_symlink() for s in binds if s.startswith(root)), binds
    assert (repo / "scratch").is_dir() and not any((repo / "scratch").iterdir())


def test_bob_run_refuses_a_symlinked_guard_log_before_emptying_anything(box, tmp_path):
    """bob-run.sh empties .bob/guard.log on the host before the run: a planted link there must be refused
    first, or the linked host file is truncated (the Oracle ab7e64d, PR #14)."""
    repo = box[0]
    victim = tmp_path / "host-file.txt"
    victim.write_text("keep me\n", encoding="utf-8")
    g = repo / ".bob" / "guard.log"
    if g.exists() or g.is_symlink():
        g.unlink()
    g.symlink_to(victim)
    r = run(box, "5", "demo", "3")
    assert r.returncode == 2 and "is a symlink" in r.stderr, r.stderr
    assert victim.read_text(encoding="utf-8") == "keep me\n" and not stub_ran(box) and row(box, 5) is None


SKELETON_DIRS = ("legacy", ".github", ".venv", "docs/bob-runs")
SKELETON_FILES = ("AGENTS.md", "BASELINE.md", "LICENSE", "docs/bob-usage.md")


def sandbox_repo(tmp_path, name):
    """A throwaway repo with every read-only path present, the real bob-sandbox.sh and a fake sudo that
    records bwrap's argv. Returns (repo, env, argv file)."""
    repo = tmp_path / name / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "bob-sandbox.sh", repo / "scripts" / "bob-sandbox.sh")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    for d in SKELETON_DIRS:
        (repo / d).mkdir(parents=True, exist_ok=True)
    for f in SKELETON_FILES:
        (repo / f).write_text("x\n", encoding="utf-8")
    fake = tmp_path / name / "bin"
    fake.mkdir()
    argv = tmp_path / name / "argv"
    (fake / "sudo").write_text(f"#!/bin/sh\nfor a in \"$@\"; do printf '%s\\n' \"$a\"; done > {argv}\n",
                               encoding="utf-8")
    (fake / "sudo").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("BOB_")}
    env.update(XDG_STATE_HOME=str(tmp_path / name / "state"), HOME=str(tmp_path / name),
               PATH=f"{fake}:{env['PATH']}")
    return repo, env, argv


def sandbox(repo, env):
    return subprocess.run(["bash", "scripts/bob-sandbox.sh", "true"], cwd=repo, env=env, capture_output=True,
                          text=True, timeout=60, check=False)


def test_every_bind_source_under_the_repo_is_refused_as_a_symlink(tmp_path):
    """Generic: record every --bind/--ro-bind source under the repo from a clean start, then plant a symlink
    at each one in turn; each start must be refused before bwrap. A bind added to the script without a
    symlink check fails here (the Oracle ab7e64d, PR #14). The repo root, .git and scripts/ are excluded,
    since this test needs them real to run at all; the check still covers them."""
    repo, env, argv = sandbox_repo(tmp_path, "clean")
    assert sandbox(repo, env).returncode == 0
    a = argv.read_text(encoding="utf-8").splitlines()
    root = str(repo.resolve())
    mounts = ("--bind", "--ro-bind", "--tmpfs")
    rels = sorted({a[j + 1][len(root) + 1:] for j, x in enumerate(a)
                   if x in mounts and a[j + 1].startswith(root + "/")} - {".git", "scripts"})
    must = {"docs", "scratch", ".bob", ".bob/guard.log", ".bob/tmp", "docs/deck", "demo", ".venv"}
    assert must <= set(rels), rels
    for k, rel in enumerate(rels):
        r2, e2, argv2 = sandbox_repo(tmp_path, f"t{k}")
        target = r2 / rel
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(tmp_path / "elsewhere")
        r = sandbox(r2, e2)
        assert r.returncode == 2 and "is a symlink" in r.stderr and not argv2.exists(), (rel, r.stderr)


@pytest.mark.parametrize("rel", ["5-demo.jsonl", "5-demo.guard.jsonl"])
def test_a_dangling_link_at_a_recording_is_refused_before_the_run(box, rel):
    """Runs are append-only, and `[ -e ]` misses a dangling symlink; cp would refuse it only after Bob ran and
    spent (the Oracle ab7e64d, PR #14). bob-run.sh must refuse it before anything runs."""
    (box[0] / "docs" / "bob-runs" / rel).symlink_to(box[2] / "nowhere")
    r = run(box, "5", "demo", "3")
    assert r.returncode == 2 and "append-only" in r.stderr, r.stderr
    assert not stub_ran(box) and row(box, 5) is None


def test_the_recheck_before_bwrap_catches_a_swap_during_setup(tmp_path):
    """The Oracle's reproducer (ab7e64d, PR #14): a fake python3 first on PATH, the one the policy check runs
    mid-setup, turns .bob/tmp into `-> ../..` after the first check. Only the re-check right before bwrap can
    refuse it; without that check, bwrap would get a writable bind of the directory above the repo."""
    repo, env, argv = sandbox_repo(tmp_path, "swap")
    fake = Path(env["PATH"].split(":")[0])
    mark = tmp_path / "swapped"
    (fake / "python3").write_text(
        "#!/bin/sh\n"
        f"if [ ! -e {mark} ]; then rm -rf .bob/tmp; ln -s ../.. .bob/tmp; : > {mark}; fi\n"
        'exec /usr/bin/python3 "$@"\n', encoding="utf-8")
    (fake / "python3").chmod(0o755)
    r = sandbox(repo, env)
    assert mark.exists(), "the swap never ran: the test would prove nothing"
    assert r.returncode == 2 and "is a symlink" in r.stderr and not argv.exists(), r.stderr


def test_the_sandbox_env_keeps_python_bytecode_on_its_own_tmp(tmp_path):
    """Python trusts a __pycache__ entry whose header claims its source's mtime and size, and Bob can write
    the tree. So the environment bob-sandbox.sh sets after --clearenv sends every Python cache read and write
    to /tmp/pycache, and that /tmp must be the start's own fresh tmpfs, never a bind, so nothing cached there
    outlives it (Aurora, after PR 20). scripts/sandbox-probe.sh plants a forged .pyc against the real
    sandbox."""
    repo, env, argv = sandbox_repo(tmp_path, "pyc")
    kept = tmp_path / "pyc" / "env"
    fake = Path(env["PATH"].split(":")[0])
    (fake / "sudo").write_text(              # it also keeps the env file (bob-sandbox.sh deletes it on exit)
        "#!/bin/sh\nprev=\nfor a in \"$@\"; do printf '%s\\n' \"$a\"\n"
        f"  [ \"$a\" = /run/bob-env ] && cp \"$prev\" {kept}; prev=$a\ndone > {argv}\n", encoding="utf-8")
    r = sandbox(repo, env)
    assert r.returncode == 0 and kept.exists(), r.stderr
    assert "export PYTHONPYCACHEPREFIX=/tmp/pycache" in kept.read_text(encoding="utf-8").splitlines()
    a = argv.read_text(encoding="utf-8").splitlines()
    assert "--clearenv" in a and any(x == "--tmpfs" and a[j + 1] == "/tmp" for j, x in enumerate(a[:-1])), a
    # No bwrap op puts host content at /, /tmp or the cache: every bind, link, data-file and overlay form,
    # with the offset of its destination (the Oracle's Low on #21). This test's own repo lives under /tmp,
    # so only those paths are checked.
    dest_at = {"--bind": 2, "--bind-try": 2, "--dev-bind": 2, "--dev-bind-try": 2, "--ro-bind": 2,
               "--ro-bind-try": 2, "--symlink": 2, "--file": 2, "--bind-data": 2, "--ro-bind-data": 2,
               "--overlay": 3, "--tmp-overlay": 1, "--ro-overlay": 1}
    dests = [a[j + dest_at[x]] for j, x in enumerate(a) if x in dest_at and j + dest_at[x] < len(a)]
    assert "/home/bob" in dests                                        # the table does read destinations
    bad = ("/", "/tmp", "/tmp/pycache")
    assert not [d for d in dests if d in bad or d.startswith("/tmp/pycache/")], dests


def test_every_start_purges_the_trees_pycache_before_bwrap(tmp_path):
    """A .pyc left in the tree must not survive into a start (the lead and Aurora's Oracle, on #21):
    - every __pycache__ directory, and any symlink named __pycache__, is gone before bwrap runs;
    - a link's own target, and a __pycache__ reached only through a linked directory, are outside the tree
      and stay untouched;
    - .venv/ (read-only to Bob) and scratch/ (never written) are not walked."""
    repo, env, argv = sandbox_repo(tmp_path, "purge")
    outside = tmp_path / "purge" / "outside"
    (outside / "__pycache__").mkdir(parents=True)
    (outside / "__pycache__" / "keep.pyc").write_bytes(b"outside")
    (outside / "data.txt").write_text("keep\n", encoding="utf-8")
    plants = [repo / "__pycache__", repo / "faxconsole" / "__pycache__", repo / "a" / "b" / "__pycache__",
              repo / ".bob" / "tmp" / "__pycache__"]
    for p in plants:
        p.mkdir(parents=True)
        (p / "m.cpython-314.pyc").write_bytes(b"planted")
    (repo / "faxconsole" / "m.py").write_text("X = 1\n", encoding="utf-8")
    (repo / "tests").mkdir()
    link = repo / "tests" / "__pycache__"
    link.symlink_to(outside)                                          # the link goes; its target stays
    (repo / "linked").symlink_to(outside)                             # not the tree's: never walked into
    kept = [repo / ".venv" / "lib" / "__pycache__" / "k.pyc", repo / "scratch" / "__pycache__" / "k.pyc"]
    for k in kept:
        k.parent.mkdir(parents=True)
        k.write_bytes(b"kept")
    r = sandbox(repo, env)
    assert r.returncode == 0 and argv.exists(), r.stderr
    assert not [p for p in plants if p.exists()] and not link.is_symlink() and not link.exists()
    assert (outside / "__pycache__" / "keep.pyc").exists() and (outside / "data.txt").exists()
    assert (repo / "linked").is_symlink() and (repo / "faxconsole" / "m.py").exists()
    assert all(k.exists() for k in kept), kept


def test_a_tracked_file_in_a_pycache_stops_the_start_and_nothing_is_purged(tmp_path):
    """Only cache artifacts are purged: a __pycache__ that holds a tracked file is not one. The start stops
    before bwrap, and since every check runs before the first deletion, nothing is deleted (the lead, on
    #21)."""
    repo, env, argv = sandbox_repo(tmp_path, "tracked")
    # Caches around the tracked one, in several directories: a purge that deleted as it went would, in almost
    # any walk order, have removed one of them before reaching the tracked file.
    caches = [repo / d / "__pycache__" / "m.cpython-314.pyc" for d in ("aa", "faxconsole", "tests", "zz")]
    for c in caches:
        c.parent.mkdir(parents=True)
        c.write_bytes(b"cache")
    tracked = repo / "mm" / "__pycache__" / "notes.txt"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", str(tracked)], cwd=repo, check=True)
    r = sandbox(repo, env)
    assert r.returncode == 2 and "holds a tracked file" in r.stderr and not argv.exists(), r.stderr
    assert tracked.exists() and all(c.exists() for c in caches)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can list a mode-000 directory, so find would not fail")
def test_a_failed_pycache_listing_stops_the_start_and_nothing_is_purged(tmp_path):
    """The purge fails closed: if find cannot list the whole tree, the start stops before bwrap and nothing is
    deleted (the standing Oracle, on #21). A directory nobody may read makes find fail."""
    repo, env, argv = sandbox_repo(tmp_path, "unlisted")
    cache = repo / "faxconsole" / "__pycache__" / "m.cpython-314.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"cache")
    locked = repo / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        r = sandbox(repo, env)
    finally:
        locked.chmod(0o755)
    assert r.returncode == 2 and "could not all be listed" in r.stderr and not argv.exists(), r.stderr
    assert cache.exists()


def test_an_unreadable_git_index_stops_the_start_and_nothing_is_purged(tmp_path):
    """The tracked-file check fails closed too. When git cannot read its index, ls-files prints nothing and
    fails; ignoring that failure read as "nothing tracked", and a tracked file was purged (Aurora's Oracle,
    on #21). Now the start stops before bwrap, and nothing is deleted."""
    repo, env, argv = sandbox_repo(tmp_path, "badindex")
    tracked = repo / "pkg" / "__pycache__" / "notes.txt"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", str(tracked)], cwd=repo, check=True)
    (repo / ".git" / "index").write_bytes(b"DIRC-short")                # a truncated index
    control = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, check=False)
    assert control.returncode != 0, "git still reads the index: the test would prove nothing"
    r = sandbox(repo, env)
    assert r.returncode == 2 and "cannot check" in r.stderr and not argv.exists(), r.stderr
    assert tracked.exists()


@pytest.mark.parametrize("var", ["GIT_INDEX_FILE", "GIT_DIR"])
def test_an_inherited_git_index_or_dir_cannot_hide_a_tracked_file(tmp_path, var):
    """The tracked-file check must read this tree's own index. A caller's private GIT_INDEX_FILE, or a hook's
    GIT_DIR, would show an index in which the tracked file is absent, and the file would be purged (the
    standing Oracle's Low on #21). bob-sandbox.sh unsets both before its first git call."""
    repo, env, argv = sandbox_repo(tmp_path, var.lower())
    tracked = repo / "pkg" / "__pycache__" / "notes.txt"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", str(tracked)], cwd=repo, check=True)
    other = tmp_path / var.lower() / "other"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    value = str(other / ".git" / "index") if var == "GIT_INDEX_FILE" else str(other / ".git")
    env = {**env, var: value}
    shown = subprocess.run(["git", "ls-files"], cwd=repo, env=env, capture_output=True, text=True,
                           check=False)
    assert shown.returncode == 0 and shown.stdout == "", "the inherited index lists the file: proves nothing"
    r = sandbox(repo, env)
    assert r.returncode == 2 and "holds a tracked file" in r.stderr and not argv.exists(), r.stderr
    assert tracked.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can list a mode-000 directory")
@pytest.mark.parametrize("d", [".claude", ".agents"])
def test_an_unlistable_skills_dir_stops_the_start(tmp_path, d):
    """A skills directory that cannot be listed might hold a skill, so the start stops. The old check read an
    ls failure as "empty" (drift-gems, after #21). The purge's own listing would refuse it too; this test
    pins the skills check's own refusal."""
    repo, env, argv = sandbox_repo(tmp_path, d.strip("."))
    sk = repo / d
    sk.mkdir()
    sk.chmod(0)
    try:
        r = sandbox(repo, env)
    finally:
        sk.chmod(0o755)
    msg = f"cannot list {repo.resolve() / d}"
    assert r.returncode == 2 and msg in r.stderr and not argv.exists(), r.stderr


def test_the_sandbox_purges_again_after_the_run_and_keeps_its_exit_code(tmp_path):
    """Nothing a run leaves in a __pycache__ outlives it on the host: the sandbox purges again once the run
    ends. The run's own exit code is kept, since bob-run.sh records it in the ledger (the lead, after #21).
    The fake sudo stands in for the run: it plants a cache, marks that it did, and exits 3."""
    repo, env, argv = sandbox_repo(tmp_path, "after")
    fake = Path(env["PATH"].split(":")[0])
    cache, mark = repo / "faxconsole" / "__pycache__", tmp_path / "after" / "planted"
    (fake / "sudo").write_text(f"#!/bin/sh\nmkdir -p {cache} && : > {cache}/m.cpython-314.pyc && : > {mark}\n"
                               "exit 3\n", encoding="utf-8")
    r = sandbox(repo, env)
    assert mark.exists(), "the run never planted: the test would prove nothing"
    assert r.returncode == 3 and not cache.exists(), r.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root can list a mode-000 directory")
def test_a_refused_purge_after_the_run_only_warns_and_the_next_start_is_refused(tmp_path):
    """A run can leave the tree unlistable, say with a mode-000 directory. The purge after the run then
    refuses: it warns and keeps the run's exit code. The next start refuses too, until the tree is fixed
    (fail closed)."""
    repo, env, argv = sandbox_repo(tmp_path, "afterref")
    fake = Path(env["PATH"].split(":")[0])
    locked = repo / "locked"
    (fake / "sudo").write_text(f"#!/bin/sh\nmkdir -p {locked} && chmod 000 {locked}\nexit 0\n",
                               encoding="utf-8")
    try:
        r = sandbox(repo, env)
        assert r.returncode == 0 and "the purge after the run refused" in r.stderr, r.stderr
        again = sandbox(repo, env)
        assert again.returncode == 2 and "could not all be listed" in again.stderr, again.stderr
    finally:
        if locked.exists():
            locked.chmod(0o755)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 directory anyway")
def test_a_run_that_leaves_unreadable_logs_keeps_its_exit_code_and_its_temp_dir_goes(tmp_path):
    """The EXIT trap copies Bob's logs and removes the per-start temp dir, which holds the env file (and the
    key, when there is one). Under set -e, a failing step there turned the run's exit code into 1 and left
    the dir on disk, and a run can cause that with a file it leaves in its own home (the standing Oracle,
    on #24). The fake sudo stands in for the run: it finds Bob's home in bwrap's argv, leaves a mode-000
    directory in its logs, and exits 3."""
    repo, env, argv = sandbox_repo(tmp_path, "trap")
    fake = Path(env["PATH"].split(":")[0])
    seen = tmp_path / "trap" / "home-seen"
    (fake / "sudo").write_text(
        "#!/bin/sh\nprev=\nfor a in \"$@\"; do [ \"$a\" = /home/bob ] && h=$prev; prev=$a; done\n"
        f"printf '%s\\n' \"$h\" > {seen}\n"
        "lk=\"$h/.bob/logs/locked\"; mkdir -p \"$lk\" && : > \"$lk/x\" && chmod 000 \"$lk\"\n"
        "exit 3\n", encoding="utf-8")
    try:
        r = sandbox(repo, env)
        home = Path(seen.read_text(encoding="utf-8").strip())
        assert home.name == "home", "the fake never found Bob's home: the test would prove nothing"
        assert r.returncode == 3, r.stderr
        assert not home.parent.exists(), "the per-start temp dir, with the env file, was left on disk"
    finally:
        subprocess.run(["chmod", "-R", "u+rwX", str(tmp_path / "trap")], check=False)
