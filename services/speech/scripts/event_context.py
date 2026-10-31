"""离线事件上下文回溯：对一个会话存档目录（raw.wav + events.jsonl），按事件时间取前后窗口。

与服务的 GET /v1/sessions/{id}/window 返回同一份 JSON，只是不用起服务。

用法：uv run python scripts/event_context.py 存档目录 --at 00:10:23 [--before 30] [--after 60] [--out 输出目录]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import soundfile as sf

from classroom_speech.timeline import TimelineIndex, format_clock, parse_clock, read_clip


def describe(w: dict, event: dict | None = None) -> str:
    """把窗口结果排成可读文本，便于在终端或展示材料里核对。"""
    head = f"事件 {event['anchor_id']}（{event['type']}）" if event else "事件"
    rows = [f"{head} @ {w['anchor']['at_clock']}，请求 {format_clock(w['requested']['from_ms'])}—{format_clock(w['requested']['to_ms'])}，"
            f"实际音频 {w['window']['from_clock']}—{w['window']['to_clock']}", "",
            "发言（会话时间 / 片段内位置 / 与事件关系 / 匿名说话人 / 方位 / 文本 / 状态）："]
    for u in w["utterances"]:
        spk = u["speaker"]["label"] if u["speaker"] else "?"
        az = f"{u['azimuth']['deg']:+.0f}°" if u["azimuth"] else "?"
        flags = [u["transcript_state"], u["reliability_state"] or ""]
        if u["overlap"]["present"]:
            flags.append("重叠:" + ",".join(u["overlap"]["with"]))
        if u["clipped_by_window"]:
            flags.append("跨窗口边界")
        off = u["offset_in_clip_ms"] / 1000
        rows.append(f"  {u['order']:>2}. {format_clock(u['start_ms'])}—{format_clock(u['end_ms'])}  {off:+6.1f}s  "
                    f"{u['relation']:<12} {spk}  {az:>5}  {u['text'] or '（无文本）'}  [{' '.join(f for f in flags if f)}]")
    rows += ["", "非发言区间："]
    rows += [f"  {format_clock(c['from_ms'])}—{format_clock(c['to_ms'])}  {c['state']}" + (f"（{c['reason']}）" if c.get("reason") else "")
             for c in w["coverage"] if c["state"] not in ("speech", "overlap")]
    rows += ["", "汇总：" + json.dumps(w["summary"], ensure_ascii=False)]
    return "\n".join(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("archive", type=Path)
    ap.add_argument("--at", required=True, help="事件时间：00:10:23 / 10:23 / 623.5（秒）")
    ap.add_argument("--before", type=float, default=30.0, help="向前秒数")
    ap.add_argument("--after", type=float, default=60.0, help="向后秒数")
    ap.add_argument("--out", type=Path, help="写 context.json / clip.wav / context.txt")
    args = ap.parse_args()

    tl = TimelineIndex.from_archive(args.archive)
    w = tl.window(parse_clock(args.at), int(args.before * 1000), int(args.after * 1000))
    text = describe(w)
    print(text)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "context.json").write_text(json.dumps(w, ensure_ascii=False, indent=2))
        (args.out / "context.txt").write_text(text + "\n")
        clip, sr = read_clip(args.archive / "raw.wav", w["window"]["from_ms"], w["window"]["to_ms"])
        sf.write(args.out / "clip.wav", clip, sr)


if __name__ == "__main__":
    main()
