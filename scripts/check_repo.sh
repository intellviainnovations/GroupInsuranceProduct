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
if grep -Ev '^\s*(#|$)' release/allowlist.txt | grep -Eq '^(\.claude|\.github|docs/(adr|specs|agents|templates|contracts|security)|scripts)/?'; then
  echo "allowlist includes internal-only paths"; fail=1
fi

# 4. Simple secret scan of tracked and not-yet-tracked (non-ignored) files, docs excluded.
# Flags private key headers, AWS-style access key ids and password literals. Matched lines are
# never printed (only file:line). Suppress a deliberate false positive by putting the marker
# "secret-scan:allow" on the same line.
secret_pattern='-----BEGIN ([A-Z]+ )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|[Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd][[:space:]]*[:=][[:space:]]*["'"'"'][^"'"'"']+["'"'"']'
secret_hits=$(git ls-files --cached --others --exclude-standard \
  | grep -Ev '^(docs/|node_modules/|frontend/node_modules/|scripts/check_repo\.sh$)|\.md$|package-lock\.json$' \
  | while IFS= read -r f; do if [ -f "$f" ]; then printf '%s\n' "$f"; fi; done \
  | xargs -r -d '\n' grep -InHE -e "$secret_pattern" 2>/dev/null \
  | grep -v 'secret-scan:allow' | cut -d: -f1,2 || true)
if [ -n "$secret_hits" ]; then
  echo "POSSIBLE SECRETS (file:line; add 'secret-scan:allow' on the line if it is a false positive):"
  echo "$secret_hits"; fail=1
fi

if [ "$fail" -ne 0 ]; then echo "check_repo: FAILED"; exit 1; fi
echo "check_repo: OK"
