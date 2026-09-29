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
# The replay surface: nothing derived from this machine may be in the public demo (the lead's rule). The
# scrub gate knows the house values. This scan knows the machine's own: temp and home paths, the repo's
# location, the host and user names (as whole words), and replay's temp-dir prefix.
python3 -I - "$out" "$root" <<'PY'
import getpass, os, re, socket, sys
out, root = sys.argv[1], sys.argv[2]
marks = [re.escape(m) for m in ("/home/", "/tmp/", root, "faxconsole-replay-")]
marks += [r"\b" + re.escape(w) + r"\b" for w in (socket.gethostname(), getpass.getuser()) if w]
pattern = re.compile("|".join(marks))
bad = set()
for d, _dirs, names in os.walk(out):
    for n in names:
        p = os.path.join(d, n)
        with open(p, "rb") as f:
            text = f.read().decode("utf-8", "replace")
        bad |= {f"{os.path.relpath(p, out)}: {m.group(0)!r}" for m in pattern.finditer(text)}
if bad:
    print("export-static.sh: refusing: machine data in the export:", *sorted(bad), sep="\n  ", file=sys.stderr)
    sys.exit(2)
PY
scripts/scrub-check.sh --paths "$out" --require-deny
echo "export-static.sh: $(find "$out" -type f | wc -l) files from $(git rev-parse --short HEAD), scrub-clean, in $out" >&2
