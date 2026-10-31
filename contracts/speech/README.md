# 语音模块共享协议

协议版本 `speech.v0.1`（语音侧首版实现，待应用侧确认后冻结为 v1）。字段定义以 `services/speech/src/classroom_speech/events.py` 为准。

| 样例 | 来源 | 说明 |
|---|---|---|
| `samples/demo_file_replay_no_asr.jsonl` | 合成课堂片段经真实语音服务处理，文件回放入口，未加载转写模型 | 含单人发言、两人重叠（分离音轨）、匿名说话人、音频可用与会话结束；`text` 为空且 `reliability_state=failed`，用于验证应用对“转写不可用”的处理 |
| `samples/demo_scene_script.json` | 合成场景脚本 | 每句的真实说话人、方位和时间，可与事件对照 |
| `samples/window_lesson_evt_001.json` | 12 分钟合成课堂，事件 00:10:23 前 30 s / 后 60 s 的上下文回溯结果 | `speech.window.v0.1`，含跨边界发言、无法识别、断流缺失；转写为测试替身 |

事件时间定位与上下文回溯的查询接口见 [`TIMELINE.md`](TIMELINE.md)（只新增查询，不改事件字段）。

所有样例均为合成数据，`data_origin` 字段如实标注；不代表真实课堂或已接通的转写能力。
