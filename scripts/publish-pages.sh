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
work=$(mktemp -d "${TMPDIR:-/var/tmp}/fax-pages.XXXXXX")
trap 'rm -rf "$work"' EXIT
scripts/export-static.sh "$work/site"
export GIT_INDEX_FILE="$work/index"
python3 -I -c 'import os, sys
top = sys.argv[1]
for d, _dirs, names in os.walk(top):
    for n in names:
        sys.stdout.write(os.path.relpath(os.path.join(d, n), top) + "\0")' "$work/site" \
  | git --work-tree="$work/site" update-index --add -z --stdin
tree=$(git write-tree)
# The parent is the remote's gh-pages as it is now, never a stale local ref, and a read that fails refuses.
# When the remote has no gh-pages (ls-remote exits 2), the commit is a root: a deleted gh-pages does not come
# back with its old history (the Oracle, on #25).
parent=""
if remote=$(git ls-remote --exit-code origin refs/heads/gh-pages); then
  parent=${remote%%[[:space:]]*}
  git fetch -q origin refs/heads/gh-pages || { echo "publish-pages.sh: refusing: cannot fetch gh-pages" >&2; exit 2; }
  fetched=$(git rev-parse --verify -q FETCH_HEAD) || { echo "publish-pages.sh: refusing: no FETCH_HEAD" >&2; exit 2; }
  [ "$fetched" = "$parent" ] || { echo "publish-pages.sh: refusing: gh-pages moved during the fetch; run it again" >&2; exit 2; }
else
  rc=$?
  [ "$rc" -eq 2 ] || { echo "publish-pages.sh: refusing: cannot read the remote's gh-pages (git ls-remote exit $rc)" >&2; exit 2; }
fi
commit=$(git commit-tree "$tree" ${parent:+-p "$parent"} -m "pages: the static replay demo, exported from ${head:0:7}")
scripts/scrub-check.sh --history "$commit" --require-deny
git push origin "$commit:refs/heads/gh-pages"
echo "publish-pages.sh: gh-pages is now ${commit:0:7}, the export of ${head:0:7}" >&2
