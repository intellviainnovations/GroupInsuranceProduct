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

# 4. Secret scan of tracked and not-yet-tracked (non-ignored) files, docs and *.md excluded.
# THIS IS A TRIPWIRE, NOT A SECRET SCANNER: it catches careless commits of obvious patterns and
# misses encoded, split, binary or unusual-format secrets. It does not replace review or a
# dedicated scanner. Matched lines are never printed (only file:line). Suppress a deliberate false
# positive (UI label, synthetic test fixture) by putting the marker "secret-scan:allow" on the same
# line; keep markers narrow. The scan fails closed: any grep error (exit status 2) fails the check.
scan_files=()
while IFS= read -r -d '' f; do
  [ -f "$f" ] && scan_files+=("$f")
done < <(git ls-files -z --cached --others --exclude-standard \
  | { grep -zEv '^(docs/|node_modules/|frontend/node_modules/|scripts/check_repo\.sh$)|\.md$|package-lock\.json$' || true; })

# Names whose assigned literal value is treated as a secret (matched case-insensitively).
secret_names='(password|passwd|pwd|secret|api[_-]?key|token)'
# 4a. Token and key formats (case-sensitive): PEM/PGP private key blocks, AWS access key ids,
#     GitHub tokens, Slack tokens, and URLs carrying a password (scheme://user:pw@host).
pat_formats='-----BEGIN ([A-Z0-9]+ )*PRIVATE KEY( BLOCK)?-----'
pat_formats+='|\b(AKIA|ASIA)[0-9A-Z]{16}\b'
pat_formats+='|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}'
pat_formats+='|\bxox[abprs]-[A-Za-z0-9-]{10,}'
pat_formats+='|[A-Za-z][A-Za-z0-9+.-]*://[^/[:space:]"'"'"'@:]+:[^/[:space:]"'"'"'@]+@'
# 4b. A secret-like name assigned a non-empty quoted literal: password = "x", "password": "x",
#     api_key='x'. Placeholders starting with $, < or { are ignored.
pat_quoted="${secret_names}[A-Za-z0-9_.-]*[\"']?[[:space:]]*[:=][[:space:]]*[\"'][^\"'\$<{[:space:]][^\"']*[\"']"
# 4c. Unquoted assignment at line start, only in config-like files (yaml, env, ini, ...), where
#     `password: x` or `API_TOKEN=x` is a real assignment rather than code such as `password: str`.
pat_unquoted="^[[:space:]]*(export[[:space:]]+)?[A-Za-z0-9_.-]*${secret_names}[A-Za-z0-9_.-]*[[:space:]]*[:=][[:space:]]*[^[:space:]\"'\$<{#[][^[:space:]]*"
config_like='(\.(ya?ml|env|ini|cfg|conf|properties|toml|sh|bash)$|(^|/)\.env|(^|/)Dockerfile)'

secret_hits=""
run_scan() { # run_scan <grep flags> <pattern> <files...>; fails closed on grep errors
  local flags=$1 pattern=$2 rc=0 out
  shift 2
  [ "$#" -gt 0 ] || return 0
  out=$(grep -InHE $flags -e "$pattern" -- "$@") || rc=$?
  if [ "$rc" -ge 2 ]; then echo "secret scan: grep failed (exit $rc); failing closed"; fail=1; return 0; fi
  if [ "$rc" -eq 0 ]; then
    out=$(printf '%s\n' "$out" | { grep -v 'secret-scan:allow' || true; } | cut -d: -f1,2)
    [ -z "$out" ] || secret_hits+="$out"$'\n'
  fi
  return 0
}
if [ "${#scan_files[@]}" -gt 0 ]; then
  config_files=()
  while IFS= read -r f; do config_files+=("$f"); done \
    < <(printf '%s\n' "${scan_files[@]}" | { grep -E "$config_like" || true; })
  run_scan "" "$pat_formats" "${scan_files[@]}"
  run_scan "-i" "$pat_quoted" "${scan_files[@]}"
  if [ "${#config_files[@]}" -gt 0 ]; then run_scan "-i" "$pat_unquoted" "${config_files[@]}"; fi
fi
if [ -n "$secret_hits" ]; then
  echo "POSSIBLE SECRETS (file:line; add 'secret-scan:allow' on the line if it is a false positive):"
  printf '%s' "$secret_hits" | sort -u; fail=1
fi

if [ "$fail" -ne 0 ]; then echo "check_repo: FAILED"; exit 1; fi
echo "check_repo: OK"
