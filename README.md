# 声音驱动的课堂学习支持系统

从课堂发言中形成可核查的学习证据，经教师确认后生成练习、提问安排与下一课教学调整。

当前已开始功能开发：DeepSeek 教学分析模块已完成首次真实调用验证，完整课堂应用尚未完成。语音位置识别和语音转文字由独立模块提供；本仓库负责接入、教学应用和角色反馈。

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
- [三版视觉原型与前端计划](docs/planning/视觉原型计划.md)
- [语音模块对接契约](docs/integration/语音模块对接契约.md)
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
