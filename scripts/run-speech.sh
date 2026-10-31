#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/logs/speech" "$ROOT/models" "$ROOT/data/audio/speech"
export PYTHONUTF8=1
export UV_CACHE_DIR="$ROOT/logs/uv-cache"
export UV_PYTHON_INSTALL_DIR="$ROOT/logs/uv-python"
export MODELSCOPE_CACHE="$ROOT/models/modelscope"
export HF_HOME="$ROOT/models/huggingface"
export TORCH_HOME="$ROOT/models/torch"
export TEMP="$(cygpath -w "$ROOT/logs/speech")"
export TMP="$TEMP"
export SPEECH_DATA_DIR="$(cygpath -w "$ROOT/data/audio/speech")"
export SPEECH_APP_URL="${SPEECH_APP_URL:-http://127.0.0.1:8000}"
if ! command -v uv >/dev/null 2>&1; then
  export PATH="$(cygpath -u "$USERPROFILE/.local/bin"):$PATH"
fi
cd "$ROOT/services/speech"
uv run --frozen --extra asr --env-file "$ROOT/.env" uvicorn classroom_speech.server:app \
  --host 127.0.0.1 --port "${SPEECH_PORT:-8765}" --app-dir "$ROOT/services/speech/src" \
  2>&1 | tee -a "$ROOT/logs/speech/server.log"
