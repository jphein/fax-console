"""scripts/publish-pages.sh publishes only the commit the go names, on the remote's gh-pages as it is now.

The Oracle's residuals on #25:
- The go names a sha: 7 to 40 lowercase hex. A one-character "SHA" used to match whatever HEAD began with.
- The parent is read from the remote with `git ls-remote`, never from a stale local ref. So a deleted gh-pages
  comes back as a root commit, not on top of its old history, and a remote the script cannot read refuses.
- A caller's GIT_* cannot point it at another repository, so the pin is checked against this one.
And its lows on #27:
- The work directory (TMPDIR) must be outside the repository, where no sandbox can write.
- Only the exact gh-pages ref counts, since ls-remote also matches the tail of other refs.

Each test runs the real script in a throwaway repo whose origin is a local bare repository. Stubs stand in
for export-static.sh, which writes a one-file site, and for the scrub gate. Each stub records its call.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECORD = 'printf "%s %s\\n" "${0##*/}" "$*" >> "$PUBLISH_TEST_CALLS"\n'
STUBS = {
    "scrub-check.sh": "#!/bin/sh\n" + RECORD,
    "export-static.sh": "#!/bin/sh\n" + RECORD + 'mkdir "$1" && printf "ok\\n" > "$1/index.html"\n',
}
IDENTITY = (("config", "user.name", "t"), ("config", "user.email", "t@example.com"))


def git(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True,
                          text=True, timeout=60, check=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A clean commit holding the real script and the stubs, with a bare origin that has no gh-pages yet.
    The identity is in the repo's config, since the script drops every GIT_*."""
    assert git(tmp_path, "init", "-q", "--bare", "-b", "main", "origin.git").returncode == 0
    r = tmp_path / "repo"
    (r / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "publish-pages.sh", r / "scripts" / "publish-pages.sh")
    for name, text in STUBS.items():
        (r / "scripts" / name).write_text(text, encoding="utf-8")
        (r / "scripts" / name).chmod(0o755)
    for args in (("init", "-q", "-b", "main"), *IDENTITY,
                 ("remote", "add", "origin", str(tmp_path / "origin.git")),
                 ("add", "scripts"), ("commit", "-q", "-m", "start")):
        assert git(r, *args).returncode == 0, args
    return r


def publish(repo: Path, want: str, **env: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    calls = repo.parent / "calls.log"
    calls.unlink(missing_ok=True)
    env = {**os.environ, "TMPDIR": str(repo.parent), "PUBLISH_TEST_CALLS": str(calls), **env}
    r = subprocess.run(["bash", "scripts/publish-pages.sh", want], cwd=repo, env=env,
                       capture_output=True, text=True, timeout=60, check=False)
    return r, (calls.read_text(encoding="utf-8").splitlines() if calls.exists() else [])


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def remote_pages(repo: Path) -> str:
    """The remote's gh-pages commit, or "" when it has none. The exact ref: ls-remote also matches a tail."""
    for line in git(repo, "ls-remote", "origin", "refs/heads/gh-pages").stdout.splitlines():
        sha, ref = line.split("\t")
        if ref == "refs/heads/gh-pages":
            return sha
    return ""


def parents(repo: Path, commit: str) -> list[str]:
    assert git(repo, "fetch", "-q", "origin", "refs/heads/gh-pages").returncode == 0
    return git(repo, "rev-list", "--parents", "-n", "1", commit).stdout.split()[1:]


def test_the_go_publishes_its_commit_as_a_root_then_on_top(repo):
    """The positive control: a 7-character sha of HEAD publishes the stub's site, first as a root commit,
    then on top of the remote's gh-pages."""
    r, calls = publish(repo, head(repo)[:7])
    assert r.returncode == 0, r.stderr
    first = remote_pages(repo)
    assert first and parents(repo, first) == []
    assert git(repo, "show", f"{first}:index.html").stdout == "ok\n"
    assert calls[0].startswith("export-static.sh "), calls
    assert calls[1] == f"scrub-check.sh --history {first} --require-deny", calls
    r, _calls = publish(repo, head(repo))                                # a full sha works as well
    assert r.returncode == 0, r.stderr
    assert parents(repo, remote_pages(repo)) == [first]


@pytest.mark.parametrize("n", [1, 6])
def test_a_short_prefix_of_head_is_refused(repo, n):
    r, calls = publish(repo, head(repo)[:n])
    assert r.returncode == 2 and "is not a commit sha" in r.stderr, (r.returncode, r.stderr)
    assert calls == [] and remote_pages(repo) == "", calls              # nothing exported, nothing pushed


def test_a_deleted_gh_pages_comes_back_as_a_root_not_on_stale_history(repo):
    """The local tracking ref still names the first publish after the remote's gh-pages is deleted. The
    next publish must not bring that history back."""
    assert publish(repo, head(repo)[:7])[0].returncode == 0
    first = remote_pages(repo)
    tracking = "+refs/heads/gh-pages:refs/remotes/origin/gh-pages"
    assert git(repo, "fetch", "-q", "origin", tracking).returncode == 0
    assert git(repo.parent / "origin.git", "update-ref", "-d", "refs/heads/gh-pages").returncode == 0
    stale = git(repo, "rev-parse", "-q", "--verify", "refs/remotes/origin/gh-pages").stdout.strip()
    assert stale == first and remote_pages(repo) == ""                  # the control: a stale local ref
    r, _calls = publish(repo, head(repo)[:7])
    assert r.returncode == 0, r.stderr
    assert parents(repo, remote_pages(repo)) == []


def test_a_remote_it_cannot_read_refuses_before_the_commit(repo):
    assert git(repo, "remote", "set-url", "origin", str(repo.parent / "no-such.git")).returncode == 0
    r, calls = publish(repo, head(repo)[:7])
    assert r.returncode == 2 and "cannot read the remote's gh-pages" in r.stderr, (r.returncode, r.stderr)
    assert not any("--history" in c for c in calls), calls              # no commit was made to scrub


def test_a_callers_git_dir_cannot_redirect_the_pin(repo, tmp_path):
    """With a caller's GIT_DIR naming another repository, the pin was checked against that repository's
    HEAD, while the export ran on this one."""
    other = tmp_path / "other"
    other.mkdir()
    for args in (("init", "-q", "-b", "main"), *IDENTITY, ("commit", "-q", "--allow-empty", "-m", "other")):
        assert git(other, *args).returncode == 0, args
    theirs = head(other)
    assert theirs != head(repo)
    r, calls = publish(repo, theirs[:7], GIT_DIR=str(other / ".git"))
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert f"HEAD is {head(repo)[:7]}, not {theirs[:7]}" in r.stderr, r.stderr
    assert calls == [] and remote_pages(repo) == "", calls


@pytest.mark.parametrize("how", ["inside", "through a symlink"])
def test_a_tmpdir_inside_the_repository_is_refused(repo, tmp_path, how):
    """The site sits in the work directory between the scrub and the push, so a sandbox that can write the
    repository must not reach it (the Oracle, on #27)."""
    inside = repo / ".bob" / "tmp"
    inside.mkdir(parents=True)
    tmpdir = inside
    if how == "through a symlink":
        tmpdir = tmp_path / "tmp-link"
        tmpdir.symlink_to(inside)
    r, calls = publish(repo, head(repo)[:7], TMPDIR=str(tmpdir))
    assert r.returncode == 2 and "is inside the repository" in r.stderr, (r.returncode, r.stderr)
    assert calls == [] and remote_pages(repo) == "", calls


def test_a_decoy_branch_does_not_block_the_publish(repo):
    """ls-remote matches its pattern against the tail of each ref, so a branch named a/refs/heads/gh-pages
    matches too, and sorts first. Only the exact ref counts (the Oracle, on #27)."""
    assert publish(repo, head(repo)[:7])[0].returncode == 0
    first = remote_pages(repo)
    assert git(repo, "push", "-q", "origin", "main:refs/heads/a/refs/heads/gh-pages").returncode == 0
    lines = git(repo, "ls-remote", "origin", "refs/heads/gh-pages").stdout.splitlines()
    assert len(lines) == 2 and lines[0].endswith("\trefs/heads/a/refs/heads/gh-pages"), lines   # the control
    r, _calls = publish(repo, head(repo)[:7])
    assert r.returncode == 0, r.stderr
    assert parents(repo, remote_pages(repo)) == [first]
