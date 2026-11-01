#!/usr/bin/env bash
# Pre-commit checks: hidden characters and internal data in staged files.
set -uo pipefail

PATTERNS_FILE="${HOME}/.config/precommit/internal-patterns"
status=0

files=$(git diff --cached --name-only --diff-filter=ACM)
[ -z "$files" ] && exit 0

for f in $files; do
  if git show ":$f" | grep -qP '[^\x00-\x7F]'; then
    echo "BLOCKED: non-ASCII characters in $f"
    git show ":$f" | grep -nP '[^\x00-\x7F]' | head -n 5
    status=1
  fi
  if [ -f "$PATTERNS_FILE" ] && git show ":$f" | grep -qEf "$PATTERNS_FILE"; then
    echo "BLOCKED: internal data in $f"
    git show ":$f" | grep -nEf "$PATTERNS_FILE" | head -n 5
    status=1
  fi
done

if [ "$status" -ne 0 ]; then
  echo "Commit stopped. Fix the lines above, then git add and commit again."
fi
exit "$status"
