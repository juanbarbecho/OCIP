#!/usr/bin/env bash
# One-time local setup: makes `git add`/`git commit` automatically strip
# notebook outputs before they reach a commit. Run this once per clone —
# git filter config lives in .git/config, not in the repo, so it doesn't
# travel with `git clone` on its own.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

git config filter.nbstrip.clean "python3 tools/nbstrip_clean.py"
git config filter.nbstrip.smudge cat
git config filter.nbstrip.required true

echo "nbstrip clean filter installed for this clone."
