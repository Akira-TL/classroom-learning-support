#!/usr/bin/env bash
set -euo pipefail
# Windows 本机服务：只停止命令行符合本项目的监听进程。
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if (( $# > 1 )); then echo "用法：stop.sh [项目原目录]" >&2; exit 2; fi
STOP_ROOT="$(cd -- "${1:-$ROOT}" && pwd)"
export CLASSROOM_WORKSPACE="$(cygpath -w "$STOP_ROOT")"
powershell.exe -NoProfile -Command '
  $workspace = $env:CLASSROOM_WORKSPACE
  foreach ($port in @(8000, 3000)) {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
      $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $listener.OwningProcess)
      $line = $process.CommandLine
      if ($line -and $line.Contains($workspace) -and
          ($line.Contains("teaching.server:application") -or $line.Contains("next"))) {
        Stop-Process -Id $listener.OwningProcess -Force
        Write-Output ("已停止项目端口 " + $port)
      } elseif ($line) {
        Write-Output ("保留其他进程占用的端口 " + $port)
      }
    }
  }
'
