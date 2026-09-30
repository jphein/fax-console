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

The export runs from the commit, never the working tree (the design the lead approved on 9/29). The sandbox
gets `git archive` of the commit on stdin, and HEAD is read once for it and for every fact. A tracked
symlink or submodule refuses. The sandboxed half (scripts/export-in-sandbox.sh, tested directly below)
extracts into a fresh directory with tar's safe flags, and checks the file count.

The tests run the real script in a throwaway repo. Stubs stand in for the steps after the checks, and each
records its call, so "refused before anything ran" is measured. test_a_clean_commit_runs_every_step is the
positive control: from a clean commit the script runs every step, so an empty record means that it refused.
"""
import ast
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from faxconsole.export import write_tar

ROOT = Path(__file__).resolve().parents[1]
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
RECORD = 'printf "%s %s\\n" "${0##*/}" "$*" >> "$EXPORT_TEST_CALLS"\n'
STUBS = {
    # The --shadow step runs after the git checks. With EXPORT_TEST_REWRITE set, it rewrites a tracked
    # fixture there, as a concurrent writer could.
    "scrub-check.sh": ("#!/bin/sh\n" + RECORD
                       + 'if [ "$1" = --shadow ] && [ -n "${EXPORT_TEST_REWRITE:-}" ]; then\n'
                       + '  printf "rewritten\\n" > tests/fixtures/capture.json\nfi\n'),
    # The sandboxed export. It keeps the archive it is handed on stdin, and its stdout is the site, as a
    # tar stream.
    "bob-sandbox.sh": ("#!/bin/sh\n" + RECORD
                       + '[ -z "${EXPORT_TEST_MOVE_HEAD:-}" ] || git commit -q --allow-empty -m moved\n'
                       + 'cat > "$EXPORT_TEST_ARCHIVE"\n'
                       + 'exec cat "$EXPORT_TEST_TAR"\n'),
}
# What the throwaway repo holds under the exported paths (faxconsole, faxcli, tests/fixtures).
COMMITTED = {"faxconsole/__init__.py": b"", "faxcli/__init__.py": b"",
             "tests/fixtures/capture.json": b'{"captured_at": "fictional"}\n'}
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
    for name, data in COMMITTED.items():
        (r / name).parent.mkdir(parents=True, exist_ok=True)
        (r / name).write_bytes(data)
    for args in (("init", "-q", "-b", "main"), ("config", "user.name", "t"),
                 ("config", "user.email", "t@example.com"),
                 ("add", "scripts", "data.txt", ".gitignore", "faxconsole", "faxcli", "tests"),
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
                            "EXPORT_TEST_TAR": str(repo.parent / "site.tar"),
                            "EXPORT_TEST_ARCHIVE": str(repo.parent / "archive.tar"), **env},
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
    top = git(repo, "rev-parse", "--show-toplevel").stdout.strip()
    built = git(repo, "log", "-1", "--format=%cd", "--date=format-local:%Y-%m-%dT%H:%M:%SZ",
                env={"TZ": "UTC"}).stdout.strip()
    r, calls = export(repo)
    assert r.returncode == 0, r.stderr
    site = repo.parent / "site"
    assert calls[0] == "scrub-check.sh --shadow", calls
    # the sandboxed half gets the venv's python, the commit's file count, and the three facts
    assert calls[1] == ("bob-sandbox.sh env PYTHONPYCACHEPREFIX=/tmp/pycache "
                        f"bash scripts/export-in-sandbox.sh {top}/.venv/bin/python "
                        f"{len(COMMITTED)} {short} main {built}"), calls
    assert calls[2:] == [f"scrub-check.sh --paths {site} --require-deny"], calls
    with tarfile.open(repo.parent / "archive.tar") as t:                  # and the commit, as an archive
        assert {m.name: t.extractfile(m).read() for m in t if m.isfile()} == COMMITTED
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


def test_the_operators_global_ignore_cannot_hide_a_planted_file(repo, tmp_path):
    """A global ignore of "*" hid a planted json.py from git status (the Oracle, on #27). The status check
    sets core.excludesFile=/dev/null, so only the repo's own .gitignore applies."""
    home = tmp_path / "home"
    (home / ".config" / "git").mkdir(parents=True)
    (home / ".config" / "git" / "ignore").write_text("*\n", encoding="utf-8")
    operator = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")}
    (repo / "json.py").write_text("planted = True\n", encoding="utf-8")
    probe = git(repo, "status", "--porcelain", env=operator)
    assert probe.returncode == 0 and probe.stdout == "", probe          # the control: that ignore hides it
    refused(export(repo, **operator), "the checkout has changes or untracked files")


def test_the_sandbox_gets_the_commit_even_if_the_tree_changes(repo):
    """The --shadow stub runs after the git checks, and rewrites a tracked fixture there, as a concurrent
    writer could. The sandbox is still handed the commit's bytes, never the tree's (the design the lead
    approved on 9/29)."""
    r, _calls = export(repo, EXPORT_TEST_REWRITE="1")
    assert r.returncode == 0, r.stderr
    assert (repo / "tests" / "fixtures" / "capture.json").read_bytes() == b"rewritten\n"   # the control
    with tarfile.open(repo.parent / "archive.tar") as t:
        assert t.extractfile("tests/fixtures/capture.json").read() == COMMITTED["tests/fixtures/capture.json"]


@pytest.mark.parametrize("kind", ["symlink", "submodule"])
def test_a_tracked_symlink_or_submodule_is_refused(repo, kind):
    """Only regular files are exported (the lead's condition 1). A tracked symlink could point the export
    anywhere, and a submodule is another repository."""
    if kind == "symlink":
        (repo / "faxconsole" / "link.py").symlink_to("../data.txt")
        assert git(repo, "add", "faxconsole/link.py").returncode == 0
    else:
        (repo / "faxcli" / "sub").mkdir()                   # an uninitialised submodule is an empty directory
        commit = git(repo, "rev-parse", "HEAD").stdout.strip()
        gitlink = f"160000,{commit},faxcli/sub"
        assert git(repo, "update-index", "--add", "--cacheinfo", gitlink).returncode == 0
    assert git(repo, "commit", "-qm", f"a tracked {kind}").returncode == 0
    probe = git(repo, "status", "--porcelain")
    assert probe.stdout == "", probe                         # the control: the checkout is clean
    r, calls = export(repo)                  # the tree's checks pass, and the commit's check refuses
    assert r.returncode == 2 and "symlinks or submodules under the exported paths" in r.stderr, r.stderr
    assert not any(c.startswith("bob-sandbox.sh") for c in calls), calls     # the sandbox never ran
    assert not (repo.parent / "site").exists()


def test_a_detached_head_is_exported_as_detached(repo):
    """HEAD is read once (the lead's condition 3). Detached, the branch fact says so, and publish-pages.sh
    refuses to publish it."""
    assert git(repo, "switch", "-q", "--detach").returncode == 0
    short = git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    r, calls = export(repo)
    assert r.returncode == 0, r.stderr
    assert f" {short} detached " in calls[1], calls


def test_the_archived_paths_cover_every_import():
    """The export runs from the archive alone, so every package that faxconsole and faxcli import must be
    in it. A new one left out would fail only at publish time, with an ImportError."""
    script = (ROOT / "scripts" / "export-static.sh").read_text(encoding="utf-8")
    archived = set(re.search(r"^paths=\(([^)]*)\)$", script, re.M).group(1).split())
    imported = set()
    for pkg in ("faxconsole", "faxcli"):
        for py in (ROOT / pkg).rglob("*.py"):
            for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    imported |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imported.add(node.module.split(".")[0])
    outside = {m for m in imported if m not in sys.stdlib_module_names}
    assert outside == {"faxconsole", "faxcli"}, outside       # the control: the scan sees both packages
    assert outside | {"tests/fixtures"} <= archived, (outside | {"tests/fixtures"}) - archived


# The sandboxed half, run directly. A stand-in python records where it ran, what it found there, and its
# arguments.
SANDBOX_HALF = ROOT / "scripts" / "export-in-sandbox.sh"
FAKE_PYTHON = '#!/bin/sh\n{ pwd; find . -type f | sort; echo "$@"; } > "$EXPORT_TEST_PYLOG"\n'


def archive_of(*members: tuple[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as t:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def in_sandbox(tmp_path: Path, archive: bytes, files) -> tuple[subprocess.CompletedProcess, str]:
    py = tmp_path / "fake-python"
    py.write_text(FAKE_PYTHON, encoding="utf-8")
    py.chmod(0o755)
    log = tmp_path / "python.log"
    argv = ["bash", str(SANDBOX_HALF), str(py), str(files), "abc1234", "main", "2026-09-29T00:00:00Z"]
    r = subprocess.run(argv, input=archive, capture_output=True, timeout=60, check=False,
                       env={**os.environ, "TMPDIR": str(tmp_path), "EXPORT_TEST_PYLOG": str(log)})
    return r, (log.read_text(encoding="utf-8") if log.exists() else "")


def test_the_sandboxed_half_exports_from_a_fresh_extraction(tmp_path):
    """The control: the files land in a fresh directory, and the export runs there with the facts."""
    archive = archive_of(("faxconsole/__init__.py", b""), ("tests/fixtures/capture.json", b"{}\n"))
    r, log = in_sandbox(tmp_path, archive, 2)
    assert r.returncode == 0, r.stderr
    cwd, *rest = log.splitlines()
    assert Path(cwd).parent == tmp_path and Path(cwd).name.startswith("src."), cwd
    assert rest == ["./faxconsole/__init__.py", "./tests/fixtures/capture.json",
                    "-S -m faxconsole.export tests/fixtures abc1234 main 2026-09-29T00:00:00Z"], rest


@pytest.mark.parametrize("case", ["a wrong count", "a parent path", "a duplicate", "not a count"])
def test_the_sandboxed_half_refuses(tmp_path, case):
    """Safe extraction and the count (the lead's condition 2). The duplicate has a count of 1, which the
    extraction would match, so only --keep-old-files refuses it."""
    archive, files, why = {
        "a wrong count": (archive_of(("a.py", b"")), 2, "extracted 1 files, the commit has 2"),
        "a parent path": (archive_of(("a.py", b""), ("../escape.py", b"")), 2, "did not extract cleanly"),
        "a duplicate": (archive_of(("a.py", b"one"), ("a.py", b"two")), 1, "did not extract cleanly"),
        "not a count": (archive_of(("a.py", b"")), "x", "FILES must be a count"),
    }[case]
    r, log = in_sandbox(tmp_path, archive, files)
    assert r.returncode == 2 and why in r.stderr.decode(), (r.returncode, r.stderr)
    assert log == ""                                          # the export never ran
    assert not (tmp_path / "escape.py").exists()              # and nothing landed outside
