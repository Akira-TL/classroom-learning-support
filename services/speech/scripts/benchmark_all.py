"""总评测：基准算法评测 + 四个方向各自的评测 + 系统级端到端评测，汇总成一个 JSON。

各方向评测脚本放在 scripts/bench_<方向>.py，暴露 run(scenes, seed) -> dict；缺失则跳过并注明。

用法：uv run python scripts/benchmark_all.py 输出目录 [--scenes 10] [--e2e-scenes 6]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).parent
DIRECTIONS = ["localization", "denoise", "separation", "math_asr"]


def load(name: str):
    path = HERE / f"bench_{name}.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"bench_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # 方向评测用多进程，子进程按模块名找函数
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--scenes", type=int, default=10)
    ap.add_argument("--e2e-scenes", type=int, default=6)
    ap.add_argument("--only", default="", help="只跑这些方向（逗号分隔），结果并入已有 benchmark_all.json")
    args = ap.parse_args()
    sys.path.insert(0, str(HERE))
    args.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    summary: dict = {"data_origin": "simulated", "sections": {}}
    only = [n for n in args.only.split(",") if n]
    if only:
        summary = json.loads((args.out / "benchmark_all.json").read_text())
    for script, extra, out_name in [] if only else [("benchmark.py", ["--scenes", str(args.scenes)], "benchmark.json"),
                                    ("e2e_eval.py", ["--scenes", str(args.e2e_scenes), "--profiles",
                                                     "baseline,only_localization,only_denoise,only_separation,integrated,integrated_enrolled_no_refine,integrated_enrolled"], "e2e.json")]:
        subprocess.run([sys.executable, str(HERE / script), str(args.out), *extra], check=True, stdout=subprocess.DEVNULL)
        summary["sections"][script.removesuffix(".py")] = json.loads((args.out / out_name).read_text())
    for name in only or DIRECTIONS:
        mod = load(name)
        if mod is None:
            summary["sections"][name] = {"status": "未交付"}
            continue
        try:
            # 各方向用自己评测的默认场景数，和它们报告的数字同条件
            summary["sections"][name] = mod.run(seed=2026)
        except Exception:  # noqa: BLE001 — 一个方向出错不影响其他方向出报告
            summary["sections"][name] = {"status": "运行失败", "error": traceback.format_exc(limit=3)}
    summary["elapsed_s"] = round(time.time() - t0, 1)
    (args.out / "benchmark_all.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"写入 {args.out / 'benchmark_all.json'}，用时 {summary['elapsed_s']} s")


if __name__ == "__main__":
    main()
