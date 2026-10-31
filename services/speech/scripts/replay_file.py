"""文件按真实速度回放为音频流：把 WAV 推给语音服务，并打印返回的事件。

用法：uv run python scripts/replay_file.py 录音.wav [--host 127.0.0.1:8765] [--speed 1.0]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import urllib.request

import numpy as np
import soundfile as sf
import websockets
from scipy.signal import resample_poly


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--host", default="127.0.0.1:8765")
    ap.add_argument("--speed", type=float, default=1.0, help="1.0 为真实速度")
    args = ap.parse_args()

    audio, sr = sf.read(args.wav, dtype="float32", always_2d=True)
    if sr != 16000:
        audio = resample_poly(audio, 16000, sr, axis=0).astype(np.float32)
    channels = min(audio.shape[1], 2)
    req = urllib.request.Request(
        f"http://{args.host}/v1/sessions",
        data=json.dumps({"channels": channels, "data_origin": "file_replay"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    sid = json.load(urllib.request.urlopen(req))["session_id"]
    print("session", sid)

    async def read_events() -> None:
        async with websockets.connect(f"ws://{args.host}/v1/sessions/{sid}/events?after=0") as ws:
            async for msg in ws:
                ev = json.loads(msg)
                print(json.dumps(ev, ensure_ascii=False))
                if ev["event_type"] == "session.ended":
                    return

    reader = asyncio.create_task(read_events())
    frame = 1600  # 100 ms
    pcm = (np.clip(audio[:, :channels], -1, 1) * 32767).astype("<i2")
    async with websockets.connect(f"ws://{args.host}/v1/sessions/{sid}/audio", max_size=None) as ws:
        for i in range(0, len(pcm), frame):
            await ws.send(pcm[i : i + frame].tobytes())
            await asyncio.sleep(0.1 / args.speed)
        await ws.send(json.dumps({"type": "end"}))
    await reader


if __name__ == "__main__":
    asyncio.run(main())
