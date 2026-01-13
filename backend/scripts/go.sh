#!/usr/bin/env bash
set -euo pipefail
if command -v go >/dev/null 2>&1; then
  exec go "$@"
fi
north55_go="${NORTH55_GO_BIN:-${HOME}/.local/share/55north-toolchains/go1.27.1/go/bin/go}"
if [[ ! -x "$north55_go" ]]; then
  printf '%s\n' 'Install Go 1.27.1 or set NORTH55_GO_BIN to the Go executable.' >&2
  exit 1
fi
exec "$north55_go" "$@"
