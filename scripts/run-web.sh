#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/logs"
if ! command -v node >/dev/null 2>&1; then
  NVM_NODE="$(cygpath -u "$LOCALAPPDATA/nvm/v24.22.2")"
  export PATH="$NVM_NODE:$PATH"
fi
cd "$ROOT/web"
export NEXT_TELEMETRY_DISABLED=1
npm run dev -- --hostname 127.0.0.1 --port 3000 2>&1 | tee -a "$ROOT/logs/web.log"
