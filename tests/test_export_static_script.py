"""scripts/export-static.sh refuses to export what it cannot show is a clean commit (Drift, on this script).

Each check before the export read an instrument's failure as a clean answer, or could:
- a failed `git status` prints nothing, so an unreadable index let a dirty checkout export;
- `git status` exits 0 with only a warning when it cannot open a directory, and Python still imports a
  package through a directory that cannot be listed;
- a status.showUntrackedFiles setting hides untracked files from `git status`;
- `find` exits non-zero when it cannot search a directory, and only set -e turned that into a refusal.
Each now refuses, with exit 2, before anything runs.

The Oracle's lows on #25:
- a caller's GIT_* could point git at another index, or add trace output the status check reads as a change,
  so the script drops every GIT_* first;
- find prunes .git and .venv, so an unreadable leftover there does not block every export;
- the surface scan refuses a directory or file it cannot read, instead of skipping it.

The tests run the real script in a throwaway repo. Stubs stand in for the steps after the checks, and each
records its call, so "refused before anything ran" is measured. test_a_clean_commit_runs_every_step is the
positive control: from a clean commit the script runs every step, so an empty record means that it refused.
"""
import io
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from faxconsole.export import write_tar

ROOT = Path(__file__).resolve().parents[1]
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
RECORD = 'printf "%s %s\\n" "${0##*/}" "$*" >> "$EXPORT_TEST_CALLS"\n'
STUBS = {
    "scrub-check.sh": "#!/bin/sh\n" + RECORD,
    # the sandboxed export: its stdout is the site, as a tar stream
    "bob-sandbox.sh": ("#!/bin/sh\n" + RECORD
                       + '[ -z "${EXPORT_TEST_MOVE_HEAD:-}" ] || git commit -q --allow-empty -m moved\n'
                       + 'exec cat "$EXPORT_TEST_TAR"\n'),
}
needs_permissions = pytest.mark.skipif(os.geteuid() == 0, reason="root lists a directory whatever its mode")


def git(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, env={**os.environ, **GIT_ENV, **(env or {})},
                          capture_output=True, text=True, timeout=60, check=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A clean commit holding the real script and untar-site.py, a stub for each tool they call next, a
    tracked file, and a .gitignore that ignores build/ and .venv/. The identity is in the repo's config,
    since the script drops every GIT_* before the stubs run."""
    r = tmp_path / "repo"
    (r / "scripts").mkdir(parents=True)
    for name in ("export-static.sh", "untar-site.py"):
        shutil.copy(ROOT / "scripts" / name, r / "scripts" / name)
    for name, text in STUBS.items():
        (r / "scripts" / name).write_text(text, encoding="utf-8")
        (r / "scripts" / name).chmod(0o755)
    (r / "data.txt").write_text("committed\n", encoding="utf-8")
    (r / ".gitignore").write_text("build/\n.venv/\n", encoding="utf-8")
    for args in (("init", "-q", "-b", "main"), ("config", "user.name", "t"),
                 ("config", "user.email", "t@example.com"), ("add", "scripts", "data.txt", ".gitignore"),
                 ("commit", "-q", "-m", "start")):
        assert git(r, *args).returncode == 0
    tar = io.BytesIO()
    write_tar({"index.html": b"ok\n"}, tar)
    (tmp_path / "site.tar").write_bytes(tar.getvalue())
    return r


def export(repo: Path, **env: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    calls = repo.parent / "calls.log"
    r = subprocess.run(["bash", "scripts/export-static.sh", str(repo.parent / "site")], cwd=repo,
                       env={**os.environ, **GIT_ENV, "EXPORT_TEST_CALLS": str(calls),
                            "EXPORT_TEST_TAR": str(repo.parent / "site.tar"), **env},
                       capture_output=True, text=True, timeout=60, check=False)
    return r, (calls.read_text(encoding="utf-8").splitlines() if calls.exists() else [])


def refused(result: tuple[subprocess.CompletedProcess, list[str]], why: str) -> None:
    r, calls = result
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert why in r.stderr, r.stderr
    assert calls == [], calls                        # neither the shadow check nor the sandbox ran
    assert not Path(r.args[2]).exists()              # and no site was written


@pytest.mark.parametrize("change", ["modified", "untracked"])
def test_a_dirty_checkout_is_refused(repo, change):
    if change == "modified":
        (repo / "data.txt").write_text("changed\n", encoding="utf-8")
    else:
        (repo / "json.py").write_text("planted = True\n", encoding="utf-8")    # python -m would import it
    refused(export(repo), "the checkout has changes or untracked files")


def test_a_failed_git_status_is_refused(repo):
    """With an unreadable index, git status fails and prints nothing, which was read as clean."""
    index = repo / ".git" / "index"
    index.write_bytes(index.read_bytes()[:20])
    probe = git(repo, "status", "--porcelain")
    assert probe.returncode != 0 and probe.stdout == "", probe     # the control: git fails, and says nothing
    refused(export(repo), "git status failed")


@needs_permissions
def test_a_directory_git_cannot_open_is_refused(repo):
    """git status exits 0 with only a warning for a directory it cannot open. Python still imports a package
    through it, so pkg/sub/__init__.py below is importable, and invisible to git."""
    sub = repo / "pkg" / "sub"
    sub.mkdir(parents=True)
    (sub / "__init__.py").write_text("planted = True\n", encoding="utf-8")
    sub.chmod(0o311)                                 # it can be passed through, not listed
    try:
        probe = git(repo, "status", "--porcelain")
        assert probe.returncode == 0 and probe.stdout == "", probe    # the control: git shows nothing
        assert probe.stderr, probe                                     # except a warning
        imported = subprocess.run(["python3", "-I", "-c", "import sys; sys.path.insert(0, '.'); "
                                   "import pkg.sub; print(pkg.sub.planted)"], cwd=repo, capture_output=True,
                                  text=True, timeout=60, check=False)
        assert imported.stdout.strip() == "True", imported             # and Python imports it all the same
        refused(export(repo), "git could not look everywhere")
    finally:
        sub.chmod(0o755)


def test_a_config_cannot_hide_untracked_files(repo):
    assert git(repo, "config", "status.showUntrackedFiles", "no").returncode == 0
    (repo / "json.py").write_text("planted = True\n", encoding="utf-8")
    probe = git(repo, "status", "--porcelain")
    assert probe.returncode == 0 and probe.stdout == "", probe         # the control: the config hides it
    refused(export(repo), "the checkout has changes or untracked files")


@needs_permissions
def test_a_directory_find_cannot_search_is_refused(repo):
    """git never opens an ignored directory, so only find sees that it cannot search build/x."""
    blind = repo / "build" / "x"
    blind.mkdir(parents=True)
    blind.chmod(0o311)
    try:
        probe = git(repo, "status", "--porcelain")
        # the control: git is clean, with no warning either
        assert (probe.returncode, probe.stdout, probe.stderr) == (0, "", ""), probe
        refused(export(repo), "find could not search the whole tree")
    finally:
        blind.chmod(0o755)


def test_a_clean_commit_runs_every_step(repo):
    """The positive control: every stub is reached, in order, and the site lands."""
    short = git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    r, calls = export(repo)
    assert r.returncode == 0, r.stderr
    site = repo.parent / "site"
    assert calls[0] == "scrub-check.sh --shadow", calls
    assert calls[1].startswith("bob-sandbox.sh env PYTHONPYCACHEPREFIX=/tmp/pycache .venv/bin/python -m "
                               f"faxconsole.export tests/fixtures {short} main "), calls
    assert calls[2:] == [f"scrub-check.sh --paths {site} --require-deny"], calls
    assert (site / "index.html").read_bytes() == b"ok\n"
    assert f"1 files from {short}, scrub-clean, in {site}" in r.stderr, r.stderr


def test_the_report_names_the_commit_that_was_exported(repo):
    """HEAD moves while the export runs: the last line still names the commit whose facts are in it."""
    short = git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    r, _calls = export(repo, EXPORT_TEST_MOVE_HEAD="1")
    assert git(repo, "rev-parse", "--short", "HEAD").stdout.strip() != short    # the control: HEAD moved
    assert r.returncode == 0, r.stderr
    assert f"files from {short}, scrub-clean" in r.stderr, r.stderr


def test_a_callers_git_index_cannot_hide_a_change(repo, tmp_path):
    """A caller's GIT_INDEX_FILE could name an index that hides a change: this one marks the modified
    data.txt skip-worktree. The script drops every GIT_* before its first git call, so it reads the repo's
    own index."""
    (repo / "data.txt").write_text("changed\n", encoding="utf-8")
    crafted = {"GIT_INDEX_FILE": str(tmp_path / "crafted-index")}
    for args in (("read-tree", "HEAD"), ("update-index", "--skip-worktree", "data.txt")):
        assert git(repo, *args, env=crafted).returncode == 0
    probe = git(repo, "status", "--porcelain", env=crafted)
    assert probe.returncode == 0 and probe.stdout == "", probe          # the control: that index hides it
    refused(export(repo, **crafted), "the checkout has changes or untracked files")


def test_a_callers_git_trace_is_not_read_as_a_change(repo):
    """Trace output goes to stderr, which the status check counts, so a caller's GIT_TRACE refused every
    export. It is dropped with the rest of GIT_*."""
    probe = git(repo, "status", "--porcelain", env={"GIT_TRACE": "1"})
    assert probe.returncode == 0 and probe.stdout == "" and probe.stderr, probe    # the control: git traces
    r, calls = export(repo, GIT_TRACE="1", GIT_TRACE2="1")
    assert r.returncode == 0, r.stderr
    assert calls[0] == "scrub-check.sh --shadow", calls


@needs_permissions
@pytest.mark.parametrize("top", [".git", ".venv"])
def test_an_unreadable_directory_in_git_or_the_venv_does_not_block_the_export(repo, top):
    """find prunes .git and .venv, which Bob cannot write, so a root-owned leftover there does not block
    every export. It still searches the rest of the tree (the find test above)."""
    blind = repo / top / "leftover"
    blind.mkdir(parents=True)
    blind.chmod(0o311)
    try:
        probe = git(repo, "status", "--porcelain")
        assert (probe.returncode, probe.stdout, probe.stderr) == (0, "", ""), probe     # git is clean
        r, calls = export(repo)
        assert r.returncode == 0, r.stderr
        assert calls[0] == "scrub-check.sh --shadow", calls
    finally:
        blind.chmod(0o755)


# Stands in for untar-site.py. It writes the site with its data file under api/. With EXPORT_TEST_BLIND set,
# it then makes api/ impossible to list, as if a later step had broken its mode.
UNTAR_STAND_IN = """import os, sys
sys.stdin.buffer.read()
api = os.path.join(sys.argv[2], "api")
os.makedirs(api)
with open(os.path.join(api, "fax.json"), "w") as f:
    f.write('{"dir": "faxconsole-replay-x1"}\\n')
if os.environ.get("EXPORT_TEST_BLIND"):
    os.chmod(api, 0o311)
"""


@needs_permissions
@pytest.mark.parametrize("blind", [False, True])
def test_the_surface_scan_refuses_what_it_cannot_read(repo, blind):
    """The file under api/ holds replay's temp-dir prefix, which the surface scan refuses. Readable, it is
    found (the control). When api/ cannot be listed, os.walk used to skip it, and the export passed as
    clean."""
    (repo / "scripts" / "untar-site.py").write_text(UNTAR_STAND_IN, encoding="utf-8")
    assert git(repo, "commit", "-qam", "a stand-in for untar-site").returncode == 0
    api = repo.parent / "site" / "api"
    try:
        r, calls = export(repo, **({"EXPORT_TEST_BLIND": "1"} if blind else {}))
    finally:
        if api.exists():
            api.chmod(0o755)
    why = "the surface scan cannot read" if blind else "machine data in the export"
    assert r.returncode == 2 and why in r.stderr, (r.returncode, r.stderr)
    assert not any("--paths" in c for c in calls), calls             # the scrub of the site never ran
