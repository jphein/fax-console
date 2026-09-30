#!/usr/bin/env bash
# export-in-sandbox.sh PYTHON FILES HASH BRANCH BUILT < commit.tar > site.tar
#
# The sandboxed half of scripts/export-static.sh, which starts it inside the OS sandbox. Its stdin is
# `git archive` of the commit's exported paths, made on the host. It is extracted into a fresh directory,
# and the export runs from there, so what is exported is the commit and never the working tree (the design
# the lead approved on 9/29).
#
# The extraction uses GNU tar's safe behaviour (measured with GNU tar 1.35):
# - a member with a '..' in its name is refused;
# - a leading '/' is stripped;
# - owners and modes are not kept (--no-same-owner, --no-same-permissions);
# - nothing is overwritten (--keep-old-files), so a duplicate member is an error.
# FILES is the number of files git lists in that commit, and the extraction must hold exactly that many.
set -euo pipefail
[ "$#" -eq 5 ] || { echo "usage: export-in-sandbox.sh PYTHON FILES HASH BRANCH BUILT < commit.tar" >&2; exit 2; }
py=$1
files=$2
shift 2
[[ $files =~ ^[1-9][0-9]*$ ]] || { echo "export-in-sandbox.sh: refusing: FILES must be a count, not '$files'" >&2; exit 2; }
src=$(mktemp -d "${TMPDIR:-/tmp}/src.XXXXXX") || { echo "export-in-sandbox.sh: refusing: no fresh directory" >&2; exit 2; }
tar -x --no-same-owner --no-same-permissions --keep-old-files -C "$src" -f - \
  || { echo "export-in-sandbox.sh: refusing: the archive did not extract cleanly" >&2; exit 2; }
got=$(find "$src" -type f | wc -l) || { echo "export-in-sandbox.sh: refusing: cannot count the extracted files" >&2; exit 2; }
[ "$got" -eq "$files" ] || { echo "export-in-sandbox.sh: refusing: extracted $got files, the commit has $files" >&2; exit 2; }
cd "$src"
# -S: no site-packages on sys.path and no sitecustomize, so the imports are the extraction's and the
# stdlib's by construction, not because the venv happens to hold nothing (the Oracle, on #29). -I is not
# used: it implies -E, which ignores PYTHONPYCACHEPREFIX, and -P, which drops the cwd (the extraction)
# from sys.path, so faxconsole would not import. -X pycache_prefix pins the bytecode cache on the
# interpreter's own command line, before any import and whatever the environment says (the Oracle, on #32):
# a .pyc in the extraction's __pycache__ is never read. /tmp is the sandbox's own fresh tmpfs. -E ignores
# every PYTHON* variable (PYTHONPATH could point zipimport, which ignores the prefix, at a tracked zip); the
# sandbox's --clearenv already drops them, and -E keeps that true if it ever stops (the Oracle, on #33).
# faxconsole.export also refuses facts unless the cache it mirrors to lies outside the extraction.
exec "$py" -S -E -X pycache_prefix=/tmp/pycache -m faxconsole.export tests/fixtures "$@"
