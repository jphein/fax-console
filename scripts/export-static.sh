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
#   status.showUntrackedFiles setting that would hide untracked files.
# - find: it exits non-zero when it cannot search a directory, including one that git ignores. It prunes
#   .git and .venv, which Bob cannot write: an unreadable directory there, such as a root-owned leftover
#   from a sudo'd pip, would otherwise block every export (the Oracle, on #25).
changes=$(git status --porcelain --untracked-files=normal 2>&1) || {
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
# The version (realm-sigil) needs the commit's facts, and the sandbox has no git: read them here. "built" is
# the commit's own time, so the same commit exports the same bytes.
hash=$(git rev-parse --short HEAD)
branch=$(git rev-parse --abbrev-ref HEAD)
built=$(TZ=UTC git log -1 --format=%cd --date=format-local:%Y-%m-%dT%H:%M:%SZ HEAD)
# PYTHONPYCACHEPREFIX: the export runs the committed code, never a .pyc planted in the tree's __pycache__
# (see scripts/test.sh; the Oracle, on PR 20).
scripts/bob-sandbox.sh env PYTHONPYCACHEPREFIX=/tmp/pycache \
  .venv/bin/python -m faxconsole.export tests/fixtures "$hash" "$branch" "$built" \
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
