# 本地 Markdown 议题规则

议题唯一权威位置为 `.scratch/`。GitHub 公开仓库仅托管代码和文档，不同时维护远程议题副本。2026年10月30日因远程标签操作再次连接中断，按用户要求采用本地议题；已有 GitHub 标签不表示启用远程工作流。

## 目录与基本操作

- 每项工作一个目录 `.scratch/<effort>/`，当前为 `.scratch/mvp/`。
- 规格按需使用 `spec.md`；现有 MVP 产品需求由 `docs/product/MVP_PRD.md` 维护，不复制正文。
- 每个议题独立为 `issues/NN-slug.md`，编号从 01 开始。
- 技能要求发布或读取议题时，创建或读取对应本地文件；跨目录使用完整路径引用。
- 状态使用顶部 `Status:`；分诊类别使用 `Category:`，遵循 `triage-labels.md`。
- 评论追加到 `## Comments`，不静默删除历史事实。
- 正式变更通过 Guard 提交；远端不可达时，本地仍是当前权威状态。

## 依赖与领取

- 阻塞用 `Blocked by: NN, NN`，没有依赖写 `Blocked by: none`。
- 跨工作目录的前置依赖使用完整相对文件链接单列在任务中；执行前必须一并检查，不能只按本目录编号判断可执行。
- 所有阻塞议题均为 `Status: resolved` 时解除阻塞。
- 按编号升序查询开放、无未解决阻塞且未领取的议题。
- 开始工作时，第一项写操作将所选议题改为 `Status: claimed` 并记录 `Claimed by:`。
- 默认串行领取；文本状态不提供并发互斥，不得让多个 Agent 依靠它抢占同一议题。
- 实现议题需逐条验证验收标准，全部满足才可设为 `resolved`，不得顺带完成父规格。

## Wayfinding operations

- 规划图为 `.scratch/<effort>/map.md`，当前为 `.scratch/mvp/map.md`。
- 子议题位于同目录 `issues/`，通过 `Parent: ../map.md` 关联。
- `Type:` 固定为 research、prototype、grilling、task。
- `Status:` 固定为 open（未领取）、claimed（已领取）、resolved（已解决）。
- 开放子议题不在规划图重复列清单，直接扫描 `issues/` 查询。
- 解决时追加 `## Answer`，记录决定与依据，再设为 resolved。
- 规划图 Decisions so far 仅追加标题链接及一句摘要，决定详情只保存在议题内。
- 每次解决后重新查询依赖与领取状态；人工决策必须通过真实对话。
- 本轮只建立规划图与决策议题，不开始产品实现。
