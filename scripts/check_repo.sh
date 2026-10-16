#!/usr/bin/env bash
# Repo hygiene checks. Run before pushing; also run in CI.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
fail=0

# 1. Required scaffold files exist.
for f in CLAUDE.md README.md release/allowlist.txt docs/templates/task-handoff.md docs/templates/task-result.md; do
  [ -f "$f" ] || { echo "MISSING: $f"; fail=1; }
done

# 2. No secret-like or key material files are tracked.
bad=$(git ls-files | grep -Ei '(^|/)\.env($|\.)|\.(pem|key|p12|pfx|jks|keystore)$|id_rsa|credentials' || true)
if [ -n "$bad" ]; then
  echo "FORBIDDEN FILES TRACKED:"; echo "$bad"; fail=1
fi

# 3. Release allowlist must not include internal-only paths.
if grep -Ev '^\s*(#|$)' release/allowlist.txt | grep -Eq '^(\.claude|\.github|docs/(adr|specs|agents|templates|contracts)|scripts)/?'; then
  echo "allowlist includes internal-only paths"; fail=1
fi

if [ "$fail" -ne 0 ]; then echo "check_repo: FAILED"; exit 1; fi
echo "check_repo: OK"
