#!/usr/bin/env bash
# 把四个方向线程交付的模块拷进包里。用法：scripts/merge_contrib.sh <contrib 目录>
set -euo pipefail
SRC=${1:?contrib 目录}
PKG=$(dirname "$0")/../src/classroom_speech
for pair in localization:localization denoise:denoise_v2 separation:separation_v2 math_asr:math_asr; do
  dir=${pair%%:*}; mod=${pair##*:}
  [ -f "$SRC/$dir/$mod.py" ] && cp "$SRC/$dir/$mod.py" "$PKG/$mod.py" && echo "合并 $dir/$mod.py"
  [ "$dir" = separation ] && cp "$SRC/separation/enrolled.py" "$PKG/" && cp "$SRC/separation/crowd_scenes.py" "$(dirname "$0")/" && echo "合并 enrolled.py crowd_scenes.py"
  [ -f "$SRC/$dir/bench_$dir.py" ] && cp "$SRC/$dir/bench_$dir.py" "$(dirname "$0")/bench_$dir.py" && echo "合并 bench_$dir.py"
done
