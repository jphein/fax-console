#!/usr/bin/env bash
# publish-pages.sh SHA: publish the static replay demo, exported from commit SHA, to the gh-pages branch.
#
# Only on the lead's go, pinned to SHA: Pages is public the moment it builds. It exports afresh
# (scripts/export-static.sh), then commits the files to gh-pages with git plumbing and a private index,
# so the checkout never changes. Before the push, the scrub gate checks the new commit's history against
# the private deny-list, and the pre-push hook checks it again. CI ignores gh-pages, which holds no code.
set -euo pipefail
# A caller's GIT_* could point git at another repository, index or config (the Oracle, on #25). Nothing here
# needs one; the private index below is set after this.
unset "${!GIT_@}"
root=$(git rev-parse --show-toplevel)
cd "$root"
want=${1:?usage: scripts/publish-pages.sh SHA (the commit that the go names)}
# A sha: 7 to 40 lowercase hex. A shorter prefix would match whatever HEAD happens to begin with.
[[ $want =~ ^[0-9a-f]{7,40}$ ]] \
  || { echo "publish-pages.sh: refusing: '$want' is not a commit sha (7 to 40 lowercase hex)" >&2; exit 2; }
head=$(git rev-parse HEAD)
case "$head" in
  "$want"*) ;;
  *) echo "publish-pages.sh: refusing: HEAD is ${head:0:7}, not $want" >&2; exit 2 ;;
esac
# The site names the branch it was exported from, and that branch is main (the lead's condition 3 on the
# git-archive design). A detached HEAD or another branch refuses.
if ref=$(git symbolic-ref -q HEAD); then
  [ "$ref" = refs/heads/main ] \
    || { echo "publish-pages.sh: refusing: publish from main, not ${ref#refs/heads/}" >&2; exit 2; }
else
  rc=$?
  [ "$rc" -eq 1 ] || { echo "publish-pages.sh: refusing: cannot read HEAD (git symbolic-ref exit $rc)" >&2; exit 2; }
  echo "publish-pages.sh: refusing: HEAD is detached; publish from main" >&2; exit 2
fi
# The work directory holds the site between the scrub and the push, so it must be outside the repository,
# where no sandbox can write (the Oracle, on #27). Symlinks are resolved first.
base=$(realpath -m -- "${TMPDIR:-/var/tmp}") || { echo "publish-pages.sh: refusing: cannot resolve TMPDIR" >&2; exit 2; }
top=$(realpath -- "$root") || { echo "publish-pages.sh: refusing: cannot resolve the repository" >&2; exit 2; }
case "$base/" in
  "$top"/*) echo "publish-pages.sh: refusing: TMPDIR ($base) is inside the repository" >&2; exit 2 ;;
esac
work=$(mktemp -d "$base/fax-pages.XXXXXX")
trap 'rm -rf "$work"' EXIT
scripts/export-static.sh "$work/site"
# The export reads HEAD again, as $full, so it must name what was pinned above: the commit, and main. A HEAD
# that moved in between would otherwise publish another commit's export under this one's name (Lucid, on
# #29), and one that only changed branch would label the pinned content with another branch (the Oracle,
# on #29). The hash must be one, since an empty prefix would match any HEAD.
facts=$(python3 -I -c 'import json, sys
v = json.load(open(sys.argv[1], encoding="utf-8"))
print(v["hash"])
print(v["branch"])' "$work/site/version.json") \
  || { echo "publish-pages.sh: refusing: cannot read the export's version.json" >&2; exit 2; }
exported=${facts%%$'\n'*}
exported_branch=${facts#*$'\n'}
[[ $exported =~ ^[0-9a-f]{7,40}$ ]] \
  || { echo "publish-pages.sh: refusing: the export's hash '$exported' is not a commit sha" >&2; exit 2; }
case "$head" in
  "$exported"*) ;;
  *) echo "publish-pages.sh: refusing: the export is of $exported, not the pinned ${head:0:7}; HEAD moved" >&2; exit 2 ;;
esac
[ "$exported_branch" = main ] \
  || { echo "publish-pages.sh: refusing: the export is labelled '$exported_branch', not main; HEAD moved" >&2; exit 2; }
export GIT_INDEX_FILE="$work/index"
python3 -I -c 'import os, sys
top = sys.argv[1]
for d, _dirs, names in os.walk(top):
    for n in names:
        sys.stdout.write(os.path.relpath(os.path.join(d, n), top) + "\0")' "$work/site" \
  | git --work-tree="$work/site" update-index --add -z --stdin
tree=$(git write-tree)
# The parent is the remote's gh-pages as it is now, never a stale local ref, and a read that fails refuses.
# When the remote has no gh-pages, the commit is a root: a deleted gh-pages does not come back with its old
# history (the Oracle, on #25). ls-remote matches its pattern against the tail of each ref, so a branch
# named a/refs/heads/gh-pages matches too: only the exact ref counts (the Oracle, on #27).
remote=$(git ls-remote origin refs/heads/gh-pages) \
  || { echo "publish-pages.sh: refusing: cannot read the remote's gh-pages (git ls-remote exit $?)" >&2; exit 2; }
parent=$(awk '$2 == "refs/heads/gh-pages" { print $1 }' <<<"$remote")
if [ -n "$parent" ]; then
  git fetch -q origin refs/heads/gh-pages || { echo "publish-pages.sh: refusing: cannot fetch gh-pages" >&2; exit 2; }
  fetched=$(git rev-parse --verify -q FETCH_HEAD) || { echo "publish-pages.sh: refusing: no FETCH_HEAD" >&2; exit 2; }
  [ "$fetched" = "$parent" ] || { echo "publish-pages.sh: refusing: gh-pages moved during the fetch; run it again" >&2; exit 2; }
fi
commit=$(git commit-tree "$tree" ${parent:+-p "$parent"} -m "pages: the static replay demo, exported from ${head:0:7}")
scripts/scrub-check.sh --history "$commit" --require-deny
git push origin "$commit:refs/heads/gh-pages"
echo "publish-pages.sh: gh-pages is now ${commit:0:7}, the export of ${head:0:7}" >&2
