# GitHub 议题规则

本项目使用当前 `origin` 对应公开仓库的 GitHub Issues。使用 `gh` 命令行，显式传入 `--repo OWNER/REPO`；从远程地址读取实际仓库，不沿用其他项目仓库。

## 基本操作

- 创建：`gh issue create --repo OWNER/REPO --title TITLE --body-file FILE`。
- 读取：`gh issue view NUMBER --repo OWNER/REPO --comments`。
- 查询：`gh issue list --repo OWNER/REPO --state open --limit 1000 --json number,title,labels,assignees`。
- 评论：`gh issue comment NUMBER --repo OWNER/REPO --body-file FILE`。
- 标签：`gh issue edit NUMBER --repo OWNER/REPO --add-label LABEL`。
- 标签清单：`gh label list --repo OWNER/REPO --limit 1000 --json name,color,description`。
- 仅创建缺失标签；不覆盖已有标签的名称、颜色或说明。
- 技能要求发布规格或议题时，发布为 GitHub Issue。多行正文先写文件，再用 `--body-file`，保持真实换行。

## 拉取请求作为需求来源

PRs as a request surface: no。

## 依赖、领取与完成

先检查本机 `gh issue create --help`、`gh issue edit --help` 和非修改查询，确认是否提供原生子议题与依赖选项。不要根据版本号猜测能力。

优先使用 GitHub 原生依赖关系。命令行没有便利选项时，通过 `gh api`：

1. `GET repos/OWNER/REPO/issues/BLOCKER` 取得阻塞议题的数据库 `id`。
2. `POST repos/OWNER/REPO/issues/CHILD/dependencies/blocked_by`，整数参数 `issue_id` 为阻塞议题数据库 ID。
3. `GET repos/OWNER/REPO/issues/CHILD/dependencies/blocked_by` 查询阻塞项。

只有远程 API 确实不可用，才使用正文 `Blocked by: #N` 作为明确记录的降级方案。

领取用 `gh issue edit NUMBER --repo OWNER/REPO --add-assignee @me`。多个 Agent 共用账号时，指派只表示可见状态，不提供互斥；本项目默认串行解决决策议题。

执行议题完成前，逐条验证验收标准，记录提交与验证证据，勾选已满足项，移除 `ready-for-agent` 并关闭。不得顺带关闭父规格或规划图。

## Wayfinding operations

- 规划图是带 `wayfinder:map` 的单一议题；仅索引已解决决定，不复制决定正文。
- 决策议题使用 `wayfinder:research`、`wayfinder:prototype`、`wayfinder:grilling` 或 `wayfinder:task` 中一个类型。
- 先创建全部已明确问题，再建立原生子议题和阻塞关系。
- 附加子议题：获取子议题数据库 `id`，向 `repos/OWNER/REPO/issues/MAP/sub_issues` 发 POST，整数参数 `sub_issue_id`。
- 子议题 API 不可用时，规划图任务列表和子议题 `Part of #N` 为降级表示，并说明缺口。
- 当前可处理项是开放、无开放阻塞项且无人领取的子议题；每次解决后重新查询。
- 解决时把结论作为评论发布，关闭该决策议题，再向规划图添加标题链接和一句摘要。
- 人工决策必须经真实对话；研究结论不自动变成用户接受的技术选型。
- 对用户引用议题时使用带链接的完整标题，不单独堆砌编号。
