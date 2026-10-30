# 本地工作流角色映射

本兼容路径保存本地 Markdown 的状态与分类值，不对应 GitHub 标签。

| 角色 | 本地字段和值 | 使用方 |
|---|---|---|
| ready-for-agent | Status: ready-for-agent | to-tickets、triage |
| bug | Category: bug | triage |
| enhancement | Category: enhancement | triage |
| needs-triage | Status: needs-triage | triage |
| needs-info | Status: needs-info | triage |
| ready-for-human | Status: ready-for-human | triage |
| wontfix | Status: wontfix | triage |

Wayfinder 使用固定 Type: research、prototype、grilling、task，以及 Status: open、claimed、resolved，不经过 wayfinder 标签映射。

规划图及决策议题不自动标为 ready-for-agent；实现任务须在规格明确后另行拆解。
