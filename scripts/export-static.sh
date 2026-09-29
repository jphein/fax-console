#!/usr/bin/env bash
# export-static.sh OUT_DIR: build the static replay demo for GitHub Pages, from a clean commit.
#
# faxconsole.export renders every GET route in replay mode, from the committed and fictional fixtures.
# That runs faxconsole's code, so it runs inside the OS sandbox, after the same checks test.sh makes.
# It hands the files over as a tar stream on stdout, so they never land in a directory Bob can write.
# untar-site.py then extracts regular files only, on the host, and the scrub gate checks every one against
# the private deny-list. Publishing is a separate step (scripts/publish-pages.sh), on the lead's go only.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
cd "$root"
out=${1:?usage: scripts/export-static.sh OUT_DIR (new or empty)}
# An export is of a commit. An untracked file counts as a change here, because a planted json.py would
# be imported by `python -m faxconsole.export` too.
if [ -n "$(git status --porcelain)" ]; then
  echo "export-static.sh: refusing: the checkout has changes or untracked files; export a commit" >&2
  exit 2
fi
stray=$(find . \( -name '*.pyc' -o -name '*.so' \) -not -path '*/__pycache__/*' -not -path './.venv/*' -not -path './.git/*' -print -quit)
[ -z "$stray" ] || { echo "export-static.sh: refusing: stray bytecode or an extension module: $stray" >&2; exit 2; }
scripts/scrub-check.sh --shadow >/dev/null 2>&1 || { echo "export-static.sh: refusing: the shadow check failed (see scripts/test.sh)" >&2; exit 2; }
scripts/bob-sandbox.sh .venv/bin/python -m faxconsole.export tests/fixtures | python3 -I scripts/untar-site.py - "$out"
scripts/scrub-check.sh --paths "$out" --require-deny
echo "export-static.sh: $(find "$out" -type f | wc -l) files from $(git rev-parse --short HEAD), scrub-clean, in $out" >&2
