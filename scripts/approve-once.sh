#!/usr/bin/env bash
# approve-once.sh -- OWNER-SIDE one-shot grant for a gated MCP call.
#
# Run this yourself when the agent asks for permission to send an email, share
# a Drive file, change a permission or delete something. It writes a grant that
# scripts/hooks/mcp-write-gate.mjs consumes on the NEXT matching call and then
# deletes: one call, then the gate is closed again.
#
# The agent must never run this. The whole point of the gate is that the
# permission comes from you and not from the thing being permitted, so an
# instruction hidden in an email or a web page cannot mint its own approval.
#
# Usage:
#   bash scripts/approve-once.sh "mcp__gmail__gmail_send_email"
#   bash scripts/approve-once.sh send_email "levél a Geodis-nak"   # substring is fine
#   bash scripts/approve-once.sh --revoke                          # withdraw a pending grant
#
# Default validity is 10 minutes; override with MINUTES=30.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GRANT_FILE="${REPO_ROOT}/store/.mcp-grant"
MINUTES="${MINUTES:-10}"

if [[ "${1:-}" == "--revoke" ]]; then
  rm -f "${GRANT_FILE}"
  echo "Visszavonva: nincs függőben lévő engedély."
  exit 0
fi

PATTERN="${1:-}"
NOTE="${2:-}"

if [[ -z "${PATTERN}" ]]; then
  echo "Használat: bash scripts/approve-once.sh <tool-név vagy minta> [megjegyzés]" >&2
  echo "Példa:     bash scripts/approve-once.sh send_email \"válasz a Geodis ajánlatra\"" >&2
  exit 1
fi

mkdir -p "${REPO_ROOT}/store"

# The pattern is stored as-is and matched case-insensitively by the gate. Escape
# nothing here: a plain tool name is already a valid regex, and a deliberately
# broad pattern is the owner's call to make.
EXPIRES="$(python3 -c "
import datetime, sys
print((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=int(sys.argv[1]))).isoformat())
" "${MINUTES}")"

python3 - "${GRANT_FILE}" "${PATTERN}" "${EXPIRES}" "${NOTE}" <<'PY'
import json, sys
path, pattern, expires, note = sys.argv[1:5]
with open(path, 'w') as f:
    json.dump({"pattern": pattern, "expires_at": expires, "note": note}, f)
PY
chmod 600 "${GRANT_FILE}"

echo "Engedély kiállítva."
echo "  minta:    ${PATTERN}"
echo "  érvényes: ${MINUTES} percig (${EXPIRES})"
echo "  hatás:    EGYETLEN egyező hívás megy át, utána a kapu automatikusan bezár."
[[ -n "${NOTE}" ]] && echo "  megjegyzés: ${NOTE}"
echo "Meggondoltad magad? bash scripts/approve-once.sh --revoke"
