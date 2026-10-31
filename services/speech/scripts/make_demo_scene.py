"""生成“平均分与四分之一”合成课堂片段（双通道 WAV），用于联调与展示。输出标注为合成数据。

用法：uv run python scripts/make_demo_scene.py 输出目录
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from classroom_speech.sim import ClassroomRoom, Placement, fan_noise, scale_to_snr, synth_speech

SCRIPT = [
    # (说话人, 方位°, 距离 m, 与上一句结束的间隔 s（负数表示抢话重叠）, 台词, 音色)
    ("教师", 0, 1.2, 0.5, "每块是四分之一吗？", {"voice": "cmn+m3", "pitch": 35, "speed": 175}),
    ("学生甲", -40, 2.5, 0.8, "有四块就是四分之一。", {"voice": "cmn+f3", "pitch": 70, "speed": 170}),
    ("学生乙", 35, 2.8, -1.6, "不对，要分得一样大。", {"voice": "cmn+f4", "pitch": 85, "speed": 175}),
    ("学生甲", -40, 2.5, 1.0, "那它没有平均分。", {"voice": "cmn+f3", "pitch": 70, "speed": 170}),
]


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    room = ClassroomRoom()
    placements, meta = [], []
    prev_end = 0.0
    for who, az, dist, gap, text, voice in SCRIPT:
        s = synth_speech(text, voice)
        t0 = round(prev_end + gap, 2)
        prev_end = t0 + len(s) / 16000
        placements.append(Placement(s, az, dist, t0))
        meta.append({"speaker": who, "azimuth_deg": az, "start_s": t0, "end_s": round(t0 + len(s) / 16000, 2), "text": text})
    length = max(m["end_s"] for m in meta) + 1.0
    images = room.render_each(placements, length)
    speech = sum(images)
    (fan,) = room.render_each([Placement(fan_noise(int(length * 16000) + 10, 16000, rng), 80, 3.5)], length)
    mix = speech + scale_to_snr(speech, fan, 5) + 0.002 * rng.standard_normal(speech.shape)
    peak = np.max(np.abs(mix)) / 0.9
    sf.write(out_dir / "demo_scene.wav", (mix / peak).T, 16000)
    for i, (m, img) in enumerate(zip(meta, images)):
        sf.write(out_dir / f"ref_{i}_{m['speaker']}.wav", img[0] / peak, 16000)
    (out_dir / "demo_scene.json").write_text(
        json.dumps({"data_origin": "simulated", "note": "espeak-ng 合成语音 + 模拟教室混响与风扇噪声，非真实课堂", "snr_db": 5, "lines": meta}, ensure_ascii=False, indent=2)
    )
    print(out_dir / "demo_scene.wav")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "../../data/audio/demo"))
