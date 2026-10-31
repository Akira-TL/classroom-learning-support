"""把已保存的事件日志（会话目录下的 events.jsonl）按 app-draft-1 推给教学应用，来源标为 recorded_result。

用于“真实语音服务的结果记录回放”。模拟数据和测试替身产生的事件会被拒绝。
令牌从环境变量 SPEECH_INGEST_TOKEN 读取，不在命令行里传。

用法：SPEECH_INGEST_TOKEN=... uv run python scripts/push_to_app.py 会话目录/events.jsonl \
          --app http://127.0.0.1:8000 --classroom 课堂标识 [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from classroom_speech.app_bridge import AppClient, AppEventMapper, SyntheticRefused, push_events
from classroom_speech.events import SpeechEvent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("events", type=Path)
    ap.add_argument("--app", default="http://127.0.0.1:8000")
    ap.add_argument("--classroom", required=True)
    ap.add_argument("--dry-run", action="store_true", help="只打印转换结果，不发送")
    args = ap.parse_args()
    events = [SpeechEvent.model_validate_json(line) for line in args.events.read_text().splitlines() if line.strip()]
    mapper = AppEventMapper(source_kind="recorded_result")
    try:
        if args.dry_run:
            for ev in events:
                for out in mapper.map(ev):
                    print(json.dumps({"classroom_id": args.classroom, "event": out}, ensure_ascii=False))
            report = mapper.report
        else:
            report = push_events(events, mapper, AppClient(args.app, os.environ.get("SPEECH_INGEST_TOKEN", ""), args.classroom))
    except SyntheticRefused as exc:
        sys.exit(f"拒绝发送：{exc}")
    print(json.dumps({"sent": report.sent, "duplicates": report.duplicates, "errors": report.errors,
                      "not_forwarded": len(report.dropped)}, ensure_ascii=False), file=sys.stderr)
    sys.exit(1 if report.errors else 0)


if __name__ == "__main__":
    main()
