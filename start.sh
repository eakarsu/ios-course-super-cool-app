#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

if [[ ! -f .env ]]; then
  printf 'ERROR: ignored .env is required; copy .env.example and supply approved local values.\n' >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source "$project_dir/.env"
set +a

for name in API_PORT UI_PORT; do
  value="${!name:-}"
  if [[ ! "$value" =~ ^[0-9]+$ ]] || (( value < 1024 || value > 65535 )); then
    printf 'ERROR: %s must be an assigned numeric port from 1024 through 65535.\n' "$name" >&2
    exit 1
  fi
done
if [[ "$API_PORT" != "31006" || "$UI_PORT" != "31007" ]]; then
  printf 'ERROR: this verification shard is assigned API/UI ports 31006/31007.\n' >&2
  exit 1
fi
if [[ "$API_PORT" == "$UI_PORT" ]]; then
  printf 'ERROR: API_PORT and UI_PORT must be distinct.\n' >&2
  exit 1
fi
if ! command -v lsof >/dev/null 2>&1; then
  printf 'ERROR: lsof is required for safe assigned-port checks.\n' >&2
  exit 1
fi
for port in "$API_PORT" "$UI_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    printf 'ERROR: assigned port %s is already occupied.\n' "$port" >&2
    exit 1
  fi
done
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  printf 'ERROR: Python 3.11 or newer is required.\n' >&2
  exit 1
fi

exec python3 -m companion.runtime
