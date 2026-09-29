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
exec scripts/bob-sandbox.sh bash -c '.venv/bin/python -m pytest -q "$@" && .venv/bin/ruff check .' test.sh "$@"
