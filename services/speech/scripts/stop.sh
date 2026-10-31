#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)"
export CLASSROOM_SPEECH_ROOT="$(cygpath -w "$ROOT/services/speech")"
export CLASSROOM_SPEECH_PORT="${SPEECH_PORT:-8765}"
powershell.exe -NoProfile -Command '
  $listeners = Get-NetTCPConnection -LocalPort $env:CLASSROOM_SPEECH_PORT -State Listen -ErrorAction SilentlyContinue
  foreach ($listener in $listeners) {
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $listener.OwningProcess)
    if ($process.CommandLine -and $process.CommandLine.Contains($env:CLASSROOM_SPEECH_ROOT) -and
        $process.CommandLine.Contains("classroom_speech.server:app")) {
      Stop-Process -Id $listener.OwningProcess -Force
      Write-Output "已停止本项目语音服务"
    } else { Write-Output "保留其他进程" }
  }
'
