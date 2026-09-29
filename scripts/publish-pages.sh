#!/usr/bin/env bash
# publish-pages.sh SHA: publish the static replay demo, exported from commit SHA, to the gh-pages branch.
#
# Only on the lead's go, pinned to SHA: Pages is public the moment it builds. It exports afresh
# (scripts/export-static.sh), then commits the files to gh-pages with git plumbing and a private index,
# so the checkout never changes. Before the push, the scrub gate checks the new commit's history against
# the private deny-list, and the pre-push hook checks it again. CI ignores gh-pages, which holds no code.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
cd "$root"
want=${1:?usage: scripts/publish-pages.sh SHA (the commit that the go names)}
head=$(git rev-parse HEAD)
case "$head" in
  "$want"*) ;;
  *) echo "publish-pages.sh: refusing: HEAD is ${head:0:7}, not $want" >&2; exit 2 ;;
esac
work=$(mktemp -d /var/tmp/fax-pages.XXXXXX)
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
git fetch -q origin gh-pages 2>/dev/null || true
parent=$(git rev-parse -q --verify refs/remotes/origin/gh-pages || true)
commit=$(git commit-tree "$tree" ${parent:+-p "$parent"} -m "pages: the static replay demo, exported from ${head:0:7}")
scripts/scrub-check.sh --history "$commit" --require-deny
git push origin "$commit:refs/heads/gh-pages"
echo "publish-pages.sh: gh-pages is now ${commit:0:7}, the export of ${head:0:7}" >&2
