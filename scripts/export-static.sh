#!/usr/bin/env bash
# export-static.sh OUT_DIR: build the static replay demo for GitHub Pages, from a clean commit.
#
# faxconsole.export renders every GET route in replay mode, from the committed and fictional fixtures.
# That runs faxconsole's code, so it runs inside the OS sandbox, after the same checks test.sh makes.
# It hands the files over as a tar stream on stdout, so they never land in a directory Bob can write.
# untar-site.py then extracts regular files only, on the host, and the scrub gate checks every one against
# the private deny-list. Publishing is a separate step (scripts/publish-pages.sh), on the lead's go only.
set -euo pipefail
# A caller's GIT_* could point git at another repository, index or config, or add trace output that the
# status check below would read as a change (the Oracle, on #25). Nothing here needs one.
unset "${!GIT_@}"
root=$(git rev-parse --show-toplevel)
cd "$root"
out=${1:?usage: scripts/export-static.sh OUT_DIR (new or empty)}
# An export is of a commit. An untracked file counts as a change here, because a planted json.py would
# be imported by `python -m faxconsole.export` too. Each check refuses when it could not look, because an
# instrument that failed must not read as clean (Drift, on this script):
# - git status: when it fails, it prints nothing. When it cannot open a directory, it exits 0 with only a
#   warning, yet Python imports a package through a directory that cannot be listed. So a failure refuses,
#   and so does anything git says, warnings included. --untracked-files=normal overrides a
#   status.showUntrackedFiles setting that would hide untracked files, and core.excludesFile=/dev/null a
#   global ignore that would (the Oracle, on #27). The repo's own .gitignore still applies.
#   core.fsmonitor=false keeps an operator's fsmonitor hook out of it: git runs that hook during status,
#   and trusts what it reports.
# - find: it exits non-zero when it cannot search a directory, including one that git ignores. It prunes
#   .git and .venv, which Bob cannot write: an unreadable directory there, such as a root-owned leftover
#   from a sudo'd pip, would otherwise block every export (the Oracle, on #25).
changes=$(git -c core.excludesFile=/dev/null -c core.fsmonitor=false status --porcelain --untracked-files=normal 2>&1) || {
  echo "export-static.sh: refusing: git status failed, so the checkout cannot be shown clean:" >&2
  head -n 20 <<<"$changes" >&2
  exit 2
}
if [ -n "$changes" ]; then
  echo "export-static.sh: refusing: the checkout has changes or untracked files, or git could not look everywhere; export a commit:" >&2
  head -n 20 <<<"$changes" >&2
  exit 2
fi
stray=$(find . \( -path ./.git -o -path ./.venv \) -prune -o \( -name '*.pyc' -o -name '*.so' \) -not -path '*/__pycache__/*' -print -quit) \
  || { echo "export-static.sh: refusing: find could not search the whole tree" >&2; exit 2; }
[ -z "$stray" ] || { echo "export-static.sh: refusing: stray bytecode or an extension module: $stray" >&2; exit 2; }
scripts/scrub-check.sh --shadow >/dev/null 2>&1 || { echo "export-static.sh: refusing: the shadow check failed (see scripts/test.sh)" >&2; exit 2; }
# The export is of the commit, never the working tree (the design the lead approved on 9/29, with three
# conditions). HEAD is read once, as $full, and the archive and every fact come from it, so nothing that
# changes the tree after the checks above can reach the export. The version (realm-sigil) needs the facts,
# and the sandbox has no git, so they are read here. "built" is the commit's own time, so the same commit
# exports the same bytes. A detached HEAD is exported as branch "detached", and publish-pages.sh refuses one.
if ref=$(git symbolic-ref -q HEAD); then
  branch=${ref#refs/heads/}
  full=$(git rev-parse --verify -q "$ref^{commit}") \
    || { echo "export-static.sh: refusing: $ref names no commit" >&2; exit 2; }
else
  rc=$?
  [ "$rc" -eq 1 ] || { echo "export-static.sh: refusing: cannot read HEAD (git symbolic-ref exit $rc)" >&2; exit 2; }
  branch=detached
  full=$(git rev-parse --verify -q 'HEAD^{commit}') \
    || { echo "export-static.sh: refusing: HEAD names no commit" >&2; exit 2; }
fi
hash=$(git rev-parse --short "$full")
built=$(TZ=UTC git log -1 --format=%cd --date=format-local:%Y-%m-%dT%H:%M:%SZ "$full")
# What the export imports and reads. tests/test_export_static_script.py holds this list to faxconsole's
# import graph.
paths=(faxconsole faxcli tests/fixtures)
for p in "${paths[@]}"; do
  [ "$(git cat-file -t "$full:$p" 2>/dev/null)" = tree ] \
    || { echo "export-static.sh: refusing: $p is not a directory at $hash" >&2; exit 2; }
done
# Only regular files are exported: a tracked symlink or submodule under those paths refuses (condition 1).
# The count is what the sandbox's extraction must hold (condition 2). A NUL cannot live in a shell
# variable, so Python reads git's list.
files=$(git ls-tree -r -z "$full" -- "${paths[@]}" | python3 -I -c '
import sys
entries = [e for e in sys.stdin.buffer.read().split(b"\0") if e]
bad = [e.split(b"\t", 1)[-1].decode("utf-8", "replace") for e in entries
       if not e.startswith((b"100644 ", b"100755 "))]
if bad:
    print("export-static.sh: refusing: symlinks or submodules under the exported paths:", *bad,
          sep="\n  ", file=sys.stderr)
    sys.exit(2)
# Bytecode is never exported: a tracked __pycache__ or .pyc/.pyo would be archived, counted and, under a
# runner that lost its cache prefix, imported instead of the source (the Oracle, on #32).
names = [e.split(b"\t", 1)[-1] for e in entries]
code = [n.decode("utf-8", "replace") for n in names
        if b"__pycache__" in n.split(b"/") or n.endswith((b".pyc", b".pyo"))]
if code:
    print("export-static.sh: refusing: bytecode under the exported paths:", *code, sep="\n  ", file=sys.stderr)
    sys.exit(2)
print(len(entries))') || { rc=$?; [ "$rc" -eq 2 ] || echo "export-static.sh: refusing: cannot list the commit's files" >&2; exit 2; }
# The sandbox gets the commit as a tar stream on stdin, extracts it into a fresh directory of its own and
# exports from there (scripts/export-in-sandbox.sh). PYTHONPYCACHEPREFIX: it never reads a .pyc planted in
# a __pycache__ (see scripts/test.sh; the Oracle, on PR 20).
git archive --format=tar "$full" -- "${paths[@]}" \
  | scripts/bob-sandbox.sh env PYTHONPYCACHEPREFIX=/tmp/pycache \
      bash scripts/export-in-sandbox.sh "$root/.venv/bin/python" "$files" "$hash" "$branch" "$built" \
  | python3 -I scripts/untar-site.py - "$out"
# The replay surface: nothing derived from this machine may be in the public demo (the lead's rule). The
# scrub gate knows the house values. This scan knows the machine's own: temp and home paths, the repo's
# location, the host and user names (as whole words), and replay's temp-dir prefix.
python3 -I - "$out" "$root" <<'PY'
import getpass, os, re, socket, sys
out, root = sys.argv[1], sys.argv[2]
marks = [re.escape(m) for m in ("/home/", "/tmp/", root, "faxconsole-replay-")]
marks += [r"\b" + re.escape(w) + r"\b" for w in (socket.gethostname(), getpass.getuser()) if w]
pattern = re.compile("|".join(marks))


def unreadable(e):
    """A directory or file this scan cannot read is refused, never skipped (the Oracle, on #25)."""
    print(f"export-static.sh: refusing: the surface scan cannot read {e.filename}: {e.strerror}", file=sys.stderr)
    sys.exit(2)


bad = set()
for d, _dirs, names in os.walk(out, onerror=unreadable):
    for n in names:
        p = os.path.join(d, n)
        try:
            with open(p, "rb") as f:
                text = f.read().decode("utf-8", "replace")
        except OSError as e:
            unreadable(e)
        bad |= {f"{os.path.relpath(p, out)}: {m.group(0)!r}" for m in pattern.finditer(text)}
if bad:
    print("export-static.sh: refusing: machine data in the export:", *sorted(bad), sep="\n  ", file=sys.stderr)
    sys.exit(2)
PY
scripts/scrub-check.sh --paths "$out" --require-deny
# The commit named is the one whose facts are in the export, even if HEAD has moved since.
files=$(find "$out" -type f | wc -l)
echo "export-static.sh: $files files from $hash, scrub-clean, in $out" >&2
