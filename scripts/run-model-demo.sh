#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/logs"
cd "$ROOT/services/application"
export PYTHONUTF8=1
export UV_CACHE_DIR="$ROOT/logs/uv-cache"
uv run --frozen --env-file "$ROOT/.env" -m teaching.demo 2>&1 | tee "$ROOT/logs/deepseek-demo.log"
