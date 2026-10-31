#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONUTF8=1
export UV_CACHE_DIR="$ROOT/logs/uv-cache"
if ! command -v uv >/dev/null 2>&1; then
  export PATH="$(cygpath -u "$USERPROFILE/.local/bin"):$PATH"
fi
cd "$ROOT/services/application"
uv run --frozen --env-file "$ROOT/.env" -m teaching.recorded_demo \
  "$ROOT/data/private/recorded-demo-20261031/materials.json" "$@"
