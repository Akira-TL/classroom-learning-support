# 工作流角色映射

采用默认名称。下游技能必须读取本表；仅创建缺失标签，保留已有标签配置。

| 角色 | GitHub 标签 | 使用方 | 含义 |
|---|---|---|---|
| ready-for-agent | ready-for-agent | to-tickets、triage | 规格明确，可进入实现 |
| bug | bug | triage | 缺陷 |
| enhancement | enhancement | triage | 功能或改进 |
| needs-triage | needs-triage | triage | 待分诊 |
| needs-info | needs-info | triage | 待补充信息 |
| ready-for-human | ready-for-human | triage | 需要人工判断或操作 |
| wontfix | wontfix | triage | 不处理 |
| wayfinder:map | wayfinder:map | wayfinder | 决策规划图 |
| wayfinder:research | wayfinder:research | wayfinder | 事实研究 |
| wayfinder:prototype | wayfinder:prototype | wayfinder | 原型验证决策 |
| wayfinder:grilling | wayfinder:grilling | wayfinder | 人工讨论决策 |
| wayfinder:task | wayfinder:task | wayfinder | 决策所需准备任务 |

规划图和决策议题不得仅因已经创建就标为 `ready-for-agent`。实现任务在规格明确后另行拆解。
