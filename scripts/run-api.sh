#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/logs"
cd "$ROOT/services/application"
export PYTHONUTF8=1
export UV_CACHE_DIR="$ROOT/logs/uv-cache"
uv run --frozen --env-file "$ROOT/.env" uvicorn teaching.server:application \
  --factory --host 127.0.0.1 --port 8000 --app-dir "$ROOT/services/application" \
  2>&1 | tee -a "$ROOT/logs/api.log"
