#!/usr/bin/env bash
set -euo pipefail
MODE="${1:-dev}"
if [[ "$#" -gt 1 || ( "$MODE" != "dev" && "$MODE" != "production" ) ]]; then
  echo "用法：bash scripts/run-web.sh [dev|production]" >&2
  exit 2
fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/logs"
if ! command -v node >/dev/null 2>&1; then
  NVM_NODE="$(cygpath -u "$LOCALAPPDATA/nvm/v24.22.2")"
  export PATH="$NVM_NODE:$PATH"
fi
cd "$ROOT/web"
export NEXT_TELEMETRY_DISABLED=1
if [[ "$MODE" == "production" ]]; then
  if [[ ! -f .next/BUILD_ID ]]; then
    echo "尚无生产构建，请先执行 npm run build --prefix web。" >&2
    exit 1
  fi
  npm run start -- --port 3000 2>&1 | tee -a "$ROOT/logs/web.log"
else
  npm run dev -- --port 3000 2>&1 | tee -a "$ROOT/logs/web.log"
fi
