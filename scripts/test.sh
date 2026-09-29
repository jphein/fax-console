#!/usr/bin/env bash
# test.sh [PYTEST ARGS...] — run the tests and the linter INSIDE the OS sandbox.
#
# Code in tests/ and faxcli/ is written with an AI agent, and a test suite executes whatever
# it contains (a conftest.py runs at collection). So on the workstation that code only ever
# runs inside scripts/bob-sandbox.sh: repo-only filesystem, no route to the LAN or loopback.
# CI runs the same suite on GitHub's disposable runners, which hold no secrets
# (permissions: contents: read) and have no route to the house network.
#
# Never run `python -m pytest` directly on the workstation.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
cd "$root"
# Sourceless bytecode outside __pycache__ (json.pyc in the root, say) would shadow a module for `python -m`,
# and .gitignore hides it from git status and diff review (the review of PR 8). An extension module (json.so)
# shadows the same way and runs native code at import, so a planted one could make the run report green.
# Refuse to run while either exists.
stray=$(find . \( -name '*.pyc' -o -name '*.so' \) -not -path '*/__pycache__/*' -not -path './.venv/*' -not -path './.git/*' -print -quit)
[ -z "$stray" ] || { echo "test.sh: refusing: sourceless bytecode or an extension module outside __pycache__: $stray" >&2; exit 2; }
# A stdlib-named module, package or symlink where Python looks first (json.py at the root, say) is imported
# instead of the real module, and every bypass of the Bob guard ends in such a file (the Oracle's delta on
# PR 11). scrub-check reads the disk, ignored files included, and runs under python3 -I itself.
# Exit 1 is a finding. Anything else means the check itself failed, and that refuses too, saying so.
rc=0; shadow=$(scripts/scrub-check.sh --shadow 2>&1) || rc=$?
if [ "$rc" -ne 0 ]; then
  printf '%s\n' "$shadow" >&2
  if [ "$rc" -eq 1 ]; then echo "test.sh: refusing: a file shadows a standard-library module" >&2
  else echo "test.sh: refusing: the shadow check itself failed (exit $rc)" >&2; fi
  exit 2
fi
# Python trusts a __pycache__ entry whose header claims the source's mtime and size, and Bob can write
# faxconsole/__pycache__, so a planted .pyc could run in place of the committed code. With the cache
# prefix on the sandbox's fresh /tmp, the tree's __pycache__ is never read or written (the Oracle, on PR
# 20). It is exported, so the tests' own Python subprocesses inherit it.
exec scripts/bob-sandbox.sh bash -c 'export PYTHONPYCACHEPREFIX=/tmp/pycache
.venv/bin/python -m pytest -q "$@" && .venv/bin/ruff check .' test.sh "$@"
