# 事件时间定位与上下文回溯：语音模块接口（speech.window.v0.1）

> 语音侧首版实现，待 Agent / 网页侧确认后冻结。事件流字段（`speech.v0.1`）没有改动，本文件只新增查询接口。
> 所有样例都是合成数据（espeak-ng 合成语音 + 模拟教室），转写来自测试替身 `oracle_script_by_time`，不代表识别准确率。

## 1. 三个模块各管什么

| 需求 | 负责方 | 状态 |
|---|---|---|
| 统一时间基准：会话毫秒 = 音频样本序号 / 16 kHz，不用网络到达时间 | 语音 | 已有，本次补上断流补齐（`mark_gap`）和墙钟换算 |
| 每段发言的起止时间、匿名说话人、方位、重叠、可靠性 | 语音 | 已有（`speech.v0.1` 事件） |
| 原始音频可索引保存（录音中也能按时间切片），服务重启后可回溯 | 语音 | **本次新增**：`raw.wav` 边收边可读，`events.jsonl` 落盘，存档可重建索引 |
| 按时间范围查询音频 + 转写 + 说话人 + 方位 | 语音 | **本次新增**：`/timeline`、`/window`、`/windows`、`/clip`、`/segments/{id}`、`/ref/{id}` |
| 保留多人同时发言、无法识别、语音缺失等状态 | 语音 | **本次新增**：窗口内逐段 `coverage`（6 种状态，无缝铺满请求窗口） |
| 识别事件、给出事件类型和时间锚点、记录多个事件 | Agent | 待 Agent 侧 |
| 按时间范围拉上下文、基于证据二次分析、不确定就标“待核验” | Agent | 待 Agent 侧（用本接口取数据） |
| 事件时间线、点击跳转、前后连续回放、同步高亮转写、教师确认 / 修正 | 网页 | 待网页侧（用本接口取数据和音频） |

语音模块只回答“这段时间里录到了什么”，不判断事件本身、不判断原因、不确认身份。

## 2. 时间基准

- 会话时间 `*_ms`：从本会话第一个音频样本起算的毫秒数，由样本计数得出。转写、声源、重叠、断流、音频切片全部用它。
- `raw.wav` 是原始双通道 16 kHz 录音，第 n 个样本就是 `n / 16` ms，可直接按时间切。
- 断流：采集端恢复后调用 `POST /v1/sessions/{id}/gap {"duration_ms": 8000}`，服务在当前位置补静音并记一条 `stream.status / gap` 事件，之后的音频仍落在正确的会话时间上（否则断流后所有时间都会提前）。
- 墙钟：建会话时传 `capture_started_unix_ms`（采集端第 0 个样本的墙钟时间）。不传时用首帧到达时间近似，`timebase.wall_clock_source` 会写明 `server_first_frame`。Agent 优先直接用会话毫秒；只有墙钟时可用 `at_unix_ms` 查询，有漂移误差。
- 界面显示用 `HH:MM:SS.mmm`（`*_clock` 字段），课堂录音的 `00:10:23` 就是 `at_ms=623000`。

## 3. 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/v1/sessions` | 新增可选字段 `capture_started_unix_ms` |
| POST | `/v1/sessions/{id}/gap` | 断流上报：`{"duration_ms", "reason"}` 补静音；或 `{"start_ms","end_ms","reason"}` 只标注损坏区间 |
| GET | `/v1/sessions/{id}/timebase` | 时间基准、已录到 / 已处理到的位置 |
| GET | `/v1/sessions/{id}/timeline?from_ms=&to_ms=` | 时间范围内全部发言与覆盖状态（网页画整节课时间线用） |
| GET | `/v1/sessions/{id}/window?at_ms=623000&before_ms=30000&after_ms=60000` | 以事件为中心的上下文（也可用 `at_unix_ms`） |
| POST | `/v1/sessions/{id}/windows` | 多个事件一次取：`[{"anchor_id":"agent_evt_001","at_ms":623000,"before_ms":30000,"after_ms":60000}, ...]`，`anchor_id` 原样带回 |
| GET | `/v1/sessions/{id}/segments/{segment_id}` | 单条发言及其时间（从发言跳到音频） |
| GET | `/v1/audio/{id}/clip?from_ms=&to_ms=&channels=mic0` | 原始录音切片 WAV；`channels=stereo` 给原始双通道供二次分析；录音进行中也可用；单次 ≤ 30 分钟 |
| GET | `/v1/audio/{id}/ref/{audio_ref_id}` | 事件里 `audio_ref.id` 对应的音轨（去噪 / 分离 / 结束后的整段原始音频） |

会话结束或服务重启后，以上查询从存档目录 `SPEECH_DATA_DIR/{session_id}/`（`raw.wav` + `events.jsonl` + `timebase.json`）重建，结果与在线时一致（有测试）。

离线等价命令：`uv run python scripts/event_context.py 存档目录 --at 00:10:23 --before 30 --after 60 --out 输出目录`。

## 4. `window` 返回什么

```jsonc
{
  "schema": "speech.window.v0.1",
  "session_id": "ses_lesson_demo", "data_origin": "simulated",
  "anchor":    {"at_ms": 623000, "at_clock": "00:10:23.000", "before_ms": 30000, "after_ms": 60000, "within_recording": true},
  "requested": {"from_ms": 593000, "to_ms": 683000},
  "window":    {"from_ms": 593000, "to_ms": 683000, "from_clock": "00:09:53.000", "to_clock": "00:11:23.000"},  // 裁到已录范围
  "recorded_until_ms": 710000, "processed_until_ms": 710000,
  "session_ended": true, "complete": true,          // false = 窗口后半段还没录到 / 还没处理完，稍后再取
  "audio": {"raw_ref": "aud_ses_lesson_demo_raw", "from_ms": 593000, "to_ms": 683000, "url": ".../v1/audio/ses_lesson_demo/clip?from_ms=593000&to_ms=683000"},
  "utterances": [{
    "segment_id": "seg_0007", "order": 6,
    "start_ms": 620260, "end_ms": 622460, "start_clock": "00:10:20.260",
    "offset_in_clip_ms": 27260,                     // 在 audio.url 片段里的播放位置；负数 = 这句在窗口开始前就开始了
    "clipped_by_window": false,
    "relation": "before", "distance_to_anchor_ms": 540,   // before | spans_anchor | after
    "text": null, "transcript_state": "unrecognized",     // recognized | unrecognized | asr_unavailable | pending | retracted
    "reliability_state": "undetermined", "status": "no_speech_recognized", "revision": 1,
    "speaker": {"label": "spk_07", "reliability_state": "needs_review", "rebind_hint": false},   // 会话内匿名标签
    "azimuth": {"deg": -29.1, "reference": "mic_pair_broadside", "reliability_state": "usable", "doa_confidence": 0.765},
    "overlap": {"present": false, "with": []},
    "audio_ref": [{"id": "aud_ses_lesson_demo_raw", "kind": "raw"}, {"id": "aud_ses_lesson_demo_seg_0007_denoised", "kind": "denoised", "offset_ms": 620260}],
    "event_ids": ["evt_…", "evt_…"]                 // 可追溯到原始 speech.v0.1 事件
  }],
  "coverage": [                                      // 无缝铺满 requested，每毫秒恰好一种状态
    {"from_ms": 593000, "to_ms": 596630, "state": "speech", "segments": ["seg_0002"]},
    {"from_ms": 640000, "to_ms": 648000, "state": "gap", "segments": [], "reason": "stream_dropout"}
  ],
  "summary": {"utterances": 10, "overlapped": 0, "recognized": 9, "unrecognized": 1, "pending": 0, "needs_review": 2,
              "speakers": ["spk_01", "…"], "speech_ms": 27800, "overlap_ms": 0, "no_speech_detected_ms": 54200,
              "gap_ms": 8000, "not_recorded_ms": 0, "not_processed_yet_ms": 0},
  "notes": ["语音模块只给出时间范围内录到的内容；时间接近不代表因果……"]
}
```

窗口里包含所有与窗口相交的发言，跨越边界的整句返回并标 `clipped_by_window`，不截断文本。同一句有修订时只返回最新修订；被撤回的保留占位（`retracted`），不从时间轴上消失。

### 覆盖状态

| state | 含义 | 应用侧怎么显示 |
|---|---|---|
| `speech` | 一个人在说 | 正常 |
| `overlap` | 两段以上发言同时进行 | 标“多人同时发言”，相关句子 `reliability_state` 至少 `needs_review` |
| `no_speech_detected` | 录到了，VAD 判为没人说话 | 不等于确认安静：小声说话可能被漏掉，可回听 |
| `gap` | 采集断流或上报损坏，音频是补的静音 | 标“音频缺失”，不能当作没人说话 |
| `not_recorded` | 会话开始前，或录音还没到达 | 窗口被裁剪 |
| `not_processed_yet` | 已录到，但这句还没说完、没出转写 | 稍后重取（`complete=false`） |

## 5. Agent 侧约定（建议）

1. 事件记录自己保存（类型、`at_ms`、识别结果、`anchor_id`），语音模块不存 Agent 事件；时间锚点用触发该事件的 `transcript.final` 的会话毫秒，避免墙钟换算误差。
2. 用 `POST /windows` 一次取多个事件的上下文；`complete=false` 时等会话往后推进再取一次。
3. 二次分析的每条结论引用证据：`segment_id` + `start_ms/end_ms`（可再附 `event_ids`）。网页据此跳转回放。
4. 只按时间先后不能下因果结论；`transcript_state != recognized`、`overlap.present`、`gap`、`no_speech_detected` 区间要在结论里写明“该段无法核实”，结论标“待核验”。
5. `spk_xx` 是会话内匿名标签，同一真实人可能被拆成多个标签（见第 7 节）；`enrolled_match` 只是线索。

## 6. 网页侧约定（建议）

1. 时间线：`GET /timeline` 画整节课的发言条与 `coverage`（重叠 / 缺失 / 无法识别用不同颜色）；Agent 事件按 `at_ms` 打点。
2. 点击事件：用 Agent 事件里的 `at_ms` 调 `/window`，播放 `audio.url`，`player.currentTime = (at_ms - window.from_ms) / 1000` 跳到事件点，前后可连续播放。
3. 同步高亮：播放位置 `t` 秒对应会话时间 `window.from_ms + t*1000`，高亮 `start_ms ≤ 它 < end_ms` 的发言（重叠时同时高亮多句）。
4. 从发言跳音频：点某句 → `start_ms`；整节课回放可在结束后用 `/ref/aud_{id}_raw`，录音进行中用 `/clip`。
5. 教师确认 / 修正结果由网页 + Agent 侧保存，语音模块不改写转写原文。

## 7. 演示与已知局限

`scripts/event_replay_demo.py` 生成约 12 分钟合成课堂（教师 + 3 名学生，风扇噪声，SNR 8 dB），在 00:10:40 断流 8 秒，Agent 在 00:10:23 报告事件，取前 30 s / 后 60 s。逐句对照剧本（`self_check.json`）：

- 窗口相交的 11 句中 10 句被定位，起点误差 −100～+430 ms（VAD 前留 200 ms 余量）；窗口外的 2 句没有返回；断流之后的发言时间没有漂移（00:10:55 那句误差 +160 ms）。
- 那句嘟囔正确保留为 `unrecognized / undetermined`，断流区间为 `gap`。
- **漏检 1 句**：学生乙 00:09:59.2 抢话，流水线没有检出第二声源（基准声源个数估计只给 1 个，整合层“个数听基准”规则把第二个方位丢了），整段算成学生甲一句、标 `usable`。这是现有重叠检测的问题，不是时间轴的问题；在原 14 秒演示场景（SNR 5 dB）里同样的抢话能检出。需要在真实录音上再评估这条规则。
- 匿名说话人不稳定：同一名学生会被拆成多个 `spk_xx`，教师在窗口两端标签不同。Agent 不应把标签不同当成不同的人。
- 转写是测试替身（按剧本时间返回台词），FunASR 尚未在 RTX 2060 上实测。
- 原始音频接口没有鉴权和过期策略，正式部署前必须加（课堂录音属于敏感数据）。
