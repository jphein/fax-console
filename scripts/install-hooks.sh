#!/usr/bin/env bash
# Install the scrub gate as this clone's pre-commit and commit-msg hooks.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
for h in pre-commit commit-msg pre-push; do
  install -m 755 "$root/scripts/hooks/$h" "$root/.git/hooks/$h"
done
echo "installed: pre-commit, commit-msg, pre-push -> scripts/scrub-check.sh"
