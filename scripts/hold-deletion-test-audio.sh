#!/usr/bin/env bash
set -euo pipefail
# 仅用于本机删除失败验收：暂时以不共享删除的方式打开一份指定音频。
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# != 2 || ! "$1" =~ ^[0-9a-f]{32}$ || ! "$2" =~ ^[0-9a-f]{32}$ ]]; then
  echo "用法：hold-deletion-test-audio.sh <临时音频资源标识> <本次验收标识>" >&2
  exit 2
fi
export CLASSROOM_LOCK_ROOT="$(cygpath -w "$ROOT")"
export CLASSROOM_LOCK_ASSET="$1"
export CLASSROOM_LOCK_RUN="$2"
powershell.exe -NoProfile -Command '
  $root = [IO.Path]::GetFullPath($env:CLASSROOM_LOCK_ROOT)
  $audio = Join-Path $root ("data/private/audio/" + $env:CLASSROOM_LOCK_ASSET + ".wav")
  $file = Get-Item -LiteralPath $audio -ErrorAction Stop
  if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "拒绝打开重解析文件" }
  $prefix = Join-Path $root ("logs/deletion-lock-" + $env:CLASSROOM_LOCK_RUN)
  $stream = [IO.File]::Open($audio, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
  try {
    [IO.File]::WriteAllText($prefix + ".ready", "ready")
    Write-Output "临时验收音频已占用；创建同标识.release文件即可释放，最长保持10分钟。"
    $deadline = [DateTime]::UtcNow.AddMinutes(10)
    while (-not (Test-Path -LiteralPath ($prefix + ".release")) -and [DateTime]::UtcNow -lt $deadline) {
      Start-Sleep -Milliseconds 200
    }
  } finally {
    $stream.Dispose()
    Write-Output "临时验收音频已释放。"
  }
'
