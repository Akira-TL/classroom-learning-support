#!/usr/bin/env bash
# 启动语音服务。环境变量：SPEECH_MIC_DISTANCE_M（麦克风间距，米）、SPEECH_ASR=funasr|none
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(cd ../.. && pwd)"
mkdir -p "$ROOT/logs/speech"
export SPEECH_DATA_DIR="${SPEECH_DATA_DIR:-$ROOT/data/audio/speech}"
nohup uv run uvicorn classroom_speech.server:app --host 127.0.0.1 --port "${SPEECH_PORT:-8765}" \
  > "$ROOT/logs/speech/server.log" 2>&1 &
echo $! > "$ROOT/logs/speech/server.pid"
echo "语音服务已启动：http://127.0.0.1:${SPEECH_PORT:-8765}/healthz（日志 logs/speech/server.log）"
