#!/usr/bin/env bash
# 前台启动，进程生命周期交由调用方管理；适用于 Windows Git Bash。
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec bash "$ROOT/scripts/run-speech.sh"
