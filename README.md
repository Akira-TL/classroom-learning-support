# 声音驱动的课堂学习支持系统

从课堂发言中形成可核查的学习证据，经教师确认后生成练习、提问安排与下一课教学调整。

当前已有可运行的本机功能验证应用：教师管理课堂、核验发言与学习证据，生成并编辑练习和教学安排，再向学生与家长发布反馈并处理疑问。权限、版本失效、采用记录、受控导出及删除已有服务端实现；完整界面验收和最终视觉仍未完成。

语音位置识别和转写由独立模块负责。当前支持明确标记的模拟语音事件，以及仅采集和传输音频的麦克风／文件流诊断；后者不返回识别结果。真实 DeepSeek 教学生成已调用验证，云端结果仍需人工检查。详细通过范围与剩余条件见[功能阶段验证记录](docs/verification/功能阶段验证记录.md)。

## 本机运行

先安装锁定依赖：后端执行 `uv sync --project services/application --frozen`；前端进入 `web/` 执行 `npm ci`。Node.js 使用本机 nvm 版本，Python 环境由 uv 维护。

根目录 `.env` 是本机配置文件，按 `.env.example` 配置 `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、至少 12 位的 `DEMO_PASSWORD`；需要受控语音接入时另配置 `SPEECH_INGEST_TOKEN`。这些变量的实际值不进入 Git，也不放入浏览器代码。

在两个 Git Bash 终端分别运行：

```sh
bash scripts/run-api.sh
bash scripts/run-web.sh
```

浏览器访问 `http://127.0.0.1:3000`，接口文档位于 `http://127.0.0.1:8000/docs`。日志进入 `logs/`，主运行数据库及私有资源位于 `data/private/`。停止时在相应终端按 Ctrl+C，或运行 `bash scripts/stop.sh`；服务只监听本机。

演示主体包括教师 `teacher-01`／`teacher-02`、学生 `student-01` 至 `student-10`、绑定 `student-01` 的家长 `parent-01` 和管理者 `admin-01`。登录密码从本机配置取得，不在网页预填。进一步说明见[本机应用运行](docs/development/本机应用运行.md)。

## 文档入口

- [原始 PRD V1.0](docs/product/声音驱动的课堂学习支持系统_PRD_V1.0.md)
- [MVP PRD](docs/product/MVP_PRD.md)
- [技术路线](docs/planning/技术路线.md)
- [演示方案](docs/planning/演示方案.md)
- [应用开发任务](.scratch/application/README.md)
- [应用开发执行约定](docs/planning/应用开发执行约定.md)
- [赛事约束与规格调整](docs/planning/赛事约束与规格调整.md)
- [DeepSeek 模型联调与运行](docs/development/模型联调.md)
- [本机应用启停与演示账号](docs/development/本机应用运行.md)
- [功能阶段验证记录](docs/verification/功能阶段验证记录.md)
- [三版视觉原型与前端计划](docs/planning/视觉原型计划.md)
- [语音模块对接契约](docs/integration/语音模块对接契约.md)
- [交给语音协作方的接入说明](docs/handoff/语音结果接入说明.md)
- [协作开发规范](docs/integration/协作开发规范.md)
- [语音团队开发入口](services/speech/README.md)
- [上游接入边界研究](docs/research/上游语音能力接入边界.md)
- [领域词汇](CONTEXT.md)

原始 PRD 保持原文。当前产品边界以 MVP PRD 中已确认事项为准，未决定的技术选择通过[本地决策规划图](.scratch/mvp/map.md)推进。

## 协作

公开仓库：[Akira-TL/classroom-learning-support](https://github.com/Akira-TL/classroom-learning-support)。议题采用 `.scratch/` 下的 Markdown 文件，随 Git 管理。`wayfinder` 用于梳理决策，不把尚未解决的技术选择直接当作实现任务。配置见[议题规则](docs/agents/issue-tracker.md)与[角色映射](docs/agents/triage-labels.md)。

安装本项目工程技能：

```text
skiloom install akira-tl/matt-skills/ask-akira --git main --scope workspace --plan --json
skiloom install akira-tl/matt-skills/ask-akira --git main --scope workspace --yes --json
```

已接受的技能状态由 Skiloom 管理。本机技能投影、运行日志、音频、模型权重和凭证不进入公开仓库。仓库公开不代表已有许可授权；本阶段不自动添加许可证。
