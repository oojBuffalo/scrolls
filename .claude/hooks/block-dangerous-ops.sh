#!/usr/bin/env bash
set -euo pipefail

INPUT="$(cat)"
COMMAND="$(printf '%s' "$INPUT" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data.get("tool_input", {}).get("command", ""))')"

DANGEROUS_PATTERNS=(
  '(^|[;&|[:space:]])sudo([[:space:]]|$)'
  '(^|[;&|[:space:]])su([[:space:]]|$)'
  'rm[[:space:]]+-rf[[:space:]]+/'
  'rm[[:space:]]+-rf[[:space:]]+~'
  'rm[[:space:]]+-rf[[:space:]]+/Users'
  'chmod[[:space:]]+-R[[:space:]]+'
  'chown[[:space:]]+-R[[:space:]]+'
  'diskutil[[:space:]]+erase'
  'diskutil[[:space:]]+partition'
  '(^|[;&|[:space:]])mkfs'
  '(^|[;&|[:space:]])dd[[:space:]].*of='
  '(^|[;&|[:space:]])shutdown([[:space:]]|$)'
  '(^|[;&|[:space:]])reboot([[:space:]]|$)'
  'launchctl[[:space:]]+(unload|bootout)'
  'git[[:space:]]+push'
  'git[[:space:]]+reset[[:space:]]+--hard'
  'git[[:space:]]+clean[[:space:]]+-'
  'git[[:space:]]+branch[[:space:]]+-D'
  'git[[:space:]]+checkout[[:space:]]+\.'
  'git[[:space:]]+restore[[:space:]]+\.'
)

for pattern in "${DANGEROUS_PATTERNS[@]}"; do
  if printf '%s' "$COMMAND" | grep -Eq "$pattern"; then
    echo "BLOCKED: command matches dangerous pattern '$pattern': $COMMAND" >&2
    exit 2
  fi
done

exit 0
