# 独立语音模块（整合版）

接收课堂双通道音频，做定位与匿名说话人跟踪、去噪、重叠检测与分离（可选声纹注册）、转写与数学语义守卫，按 `speech.v0.1` 输出事件（字段见 `src/classroom_speech/events.py`，未改动）。教学判断、真实学生身份确认和角色报告由应用侧负责。

协作规则先读：[协作开发规范](../../docs/integration/协作开发规范.md)、[语音模块对接契约](../../docs/integration/语音模块对接契约.md)、[MVP PRD](../../docs/product/MVP_PRD.md)、[上游接入边界研究](../../docs/research/上游语音能力接入边界.md)。应用当前实际接收的字段见[接入说明](../../docs/handoff/语音结果接入说明.md)与[实际支持范围](../../docs/handoff/语音接口当前支持范围.md)；本模块通过下文“接入教学应用”的转换桥对接，不直接发送 `speech.v0.1` 对象。

## 流水线

```
PCM 帧 ─► 能量 VAD 切句 ─► 定位 localize ─┬─ 1 个方位 ────────────► 三证会审去噪 ─┐
         （语音前静音 → 噪声指纹：      │                                          ├─► 匿名说话人跟踪 ─► 转写 + 数学守卫 ─► 事件
           互谱 + 功率谱）              └─ ≥2 个方位 / 有声纹注册 ─► 选择性分离 ─┘     （方位 × 声纹）    （原文不改，只降可靠性）
                                              单人区间改走去噪；声纹分路用方位锚定对齐定方位
```

| 阶段 | 模块 | 来源 | 一句话 |
|---|---|---|---|
| 定位 | `localization.py` `localize` | 方向一 | 起音加权 + 扩散场补偿 + 数字孪生反畸变，纠正混响把方位“压向正前方” |
| 跟踪 | `localization.py` `SpeakerTracker` | 方向一 | 方位与声纹各算对数似然比再相加：同方向不同嗓音 → 新标签；换座但嗓音匹配 → 沿用并提示 |
| 去噪 | `denoise_v2.py` `adaptive_denoise` | 方向二 | 三证会审门控：噪声强度 × 方向可信度 × 语音保真度，空间门先自检再上场 |
| 分离 | `separation_v2.py` + `enrolled.py` | 方向三 | 有课前声纹注册时按音色（NMF 字典）分路，可多于方位数；无注册时退回基准选择性分离 |
| 转写守卫 | `math_asr.py` `MathGuardedAsr` | 方向四 | 只盯会改变数学含义的表达：反事实热词对质 + 声调仲裁 + 题目上下文只排序不改写 |
| 组装 | `stages.py` `pipeline.py` | 整合 | 阶段插槽、基准兜底、消融开关、联动修正（见下） |

整合层自己做的三处联动修正：
1. **声源个数取共识**（`stages.consensus`）：新定位方位更准，但会把风扇报成第二声源（反畸变曲线在 ±70° 饱和），把单人片段送去分离。改为“个数听基准（扣过噪声互谱）、方位听新方案”。
2. **单人区间改走去噪**（`Profile.refine_single`）：分路后没有和别人重叠的区间，回到原始双通道做去噪，不用分离掩码。
3. **声纹分路用方位锚定对齐定方位**（`Session._anchor_streams`）：注册时的座位方位不可靠，学生也会换座；改为把每一路和指向本次各定位峰的锚定流做相关，归到最像的方位。

每个阶段缺失或导入失败时自动退回基准实现；`GET /v1/capabilities` 的 `stages` 字段如实报告每个阶段当前跑的是哪一版。

## 运行

```bash
cd services/speech
uv sync --group dev
uv run pytest -q                                   # 34 项
scripts/start.sh                                   # http://127.0.0.1:8765，健康检查 GET /healthz
scripts/stop.sh
uv run python scripts/run_demo.py 输出目录          # 端到端演示：基准 / 整合 / 整合+声纹注册 三套事件与音轨
uv run python scripts/e2e_eval.py 输出目录 --profiles baseline,integrated,integrated_enrolled
uv run python scripts/benchmark_all.py 输出目录      # 总评测：算法基准 + 端到端 + 四个方向（约 40 分钟）
```

## 接入教学应用（app-draft-1 转换桥）

应用当前只接受 `app-draft-1`（严格模型，多余字段返回 422），所以 `speech.v0.1` 事件经 `src/classroom_speech/app_bridge.py` 转换后，推到应用的可信入口 `POST /api/integrations/speech/events`。映射规则写在该文件开头。

| 配置（环境变量） | 说明 |
|---|---|
| `SPEECH_APP_URL` | 应用地址，如 `http://127.0.0.1:8000` |
| `SPEECH_INGEST_TOKEN` | 与应用侧同一个接入令牌（≥32 字符），只放 `.env`，不提交 |

两种用法：

```bash
# 1. 实时：创建会话时带上应用里的课堂标识，事件边产生边转发；GET /v1/sessions/{id}/app 查看已发送、重复、未转发及原因
curl -X POST :8765/v1/sessions -H 'Content-Type: application/json' -d '{"data_origin": "live", "app_classroom_id": "课堂标识"}'
# 2. 回放已保存的会话结果（来源标 recorded_result）
uv run python scripts/push_to_app.py 会话目录/events.jsonl --app http://127.0.0.1:8000 --classroom 课堂标识 [--dry-run]
```

- 来源：`live` / `file_replay` → `upstream_live`；回放 → `recorded_result`；`simulated` 或测试替身引擎（`oracle_*`）一律视为 `synthetic`，桥在本地拒绝发送（应用可信入口也会拒收）。
- 应用按事件标识幂等：同一批事件重发只算重复；但同一事件换来源重发会被应用 409 拒绝（实时转发过的会话不能再以 `recorded_result` 回放进同一课堂）。
- app-draft-1 目前装不下的信息不发送，逐条记在报告里：方位、`reliability_state`（含数学守卫的核验原因）、`audio_ref`、重叠对象、无文字的 final（ASR 不可用或未识别）、`audio.available`。这些需要和应用方商量协议扩展，不塞进 `source_ref` 冒充已支持。
- 已在本地实测：临时数据库起应用 → 语音会话实时转发 → 应用时间线出现 3 条发言（匿名标签进 `source_ref`、重叠标记、断流状态、结束封闭），回放与重复发送结果正确。测试 `tests/test_app_bridge.py` 直接用应用的 `SpeechEvent` 模型校验每条转换结果。

## 事件时间定位与上下文回溯

统一时间轴 = 会话毫秒（样本计数）。`raw.wav` 与 `events.jsonl` 边收边落盘，`timeline.py` 按时间范围取回
发言、匿名说话人、方位、重叠和缺失状态，并按样本切原始音频；断流用 `POST /gap` 补静音，后续时间不漂移。
接口与返回字段见 `../../contracts/speech/TIMELINE.md`。

```bash
uv run python scripts/event_replay_demo.py 输出目录                       # 12 分钟合成课堂，00:10:23 事件取前 30 s / 后 60 s
uv run python scripts/event_context.py 存档目录 --at 00:10:23 --out 输出目录  # 对任意会话存档离线回溯
```

新增接口：`POST /v1/sessions/{id}/context`（`{"question": ..., "expected_terms": [...]}`），只用于识别候选排序与核验提示，不改写原文。声纹注册目前通过 `Session(enrollment={标签: 双通道注册音频})` 传入，HTTP 接口待与应用侧约定。

## 合成语音的修正

基准 `sim.py` 用 espeak-ng 的 `cmn` 声音时，会把“四”“一”等字按英文读（four / one），之前所有合成样例里的数学关键词都是乱读的。整合版先用 pypinyin 转带调拼音，再用 `cmn-latn-pinyin` 发音。整合版的所有评测（含基准方案）都在修正后的语音上同条件重跑。

## 已知限制

- 全部结果来自 espeak-ng 合成语音 + 镜像法模拟教室，只说明相对基线的增益，不代表真实儿童课堂。
- FunASR / ClearerVoice / 神经目标说话人提取都只有适配器，未在本环境实测（无法下载权重）；端到端演示的转写是按剧本时间返回台词的测试替身 `oracle_script_by_time`。
- 声纹认人会认错或多认（注册池越大精确率越低）；匹配结果只写进 `diagnostics.enrolled_match`，并标 `needs_review`。
- 匿名说话人跟踪：先在重叠片段里出现的学生，声纹被另一人污染，之后再开口可能被开成新标签（会标 `needs_review`）。
