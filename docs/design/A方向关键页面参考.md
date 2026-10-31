# A方向关键页面参考与确认

日期：2026年10月31日。用户已明确选择 A：时间线居中。以下四张为该方向的调整稿和关键页面参考，待用户确认布局或提出修改；当前未实施完整视觉前端。

## 图稿

| 图稿 | 内容 | 需确认的重点 |
|---|---|---|
| [教师工作台第三版](prototypes/A-workbench-v3.png) | 左题目、中间时间线、右核验与证据 | 时间线作为主要操作区，原话和证据可对应 |
| [教学支持第二版](prototypes/A-teaching-v2.png) | 证据背景、三层练习编辑、提问与下一课安排 | 草稿、确认、采用分开，准备不足明确显示 |
| [发布纠错第一版](prototypes/A-publishing-v1.png) | 归属修正后旧报告失效，返回重核 | 影响范围、等待新版及离线副本限制可理解 |
| [三角色页面第二版](prototypes/A-roles-v2.png) | 学生练习、家长家庭活动、管理者汇总 | 学生和家长适合窄屏阅读，管理者无个人明细 |

## 实施约束

图稿由 imagegen 内置工具生成并按现有功能边界检查，其中教学对象改为只读，未完成逐题核验时确认和采用禁用，管理者额外权限入口已移除。它们用于确认布局、信息层次和视觉语言，不能单独扩大已有功能。

- 教师工作台的文字核验只判断文本，学生选择属于身份核验；图中第一行重复出现的学生控件在实现时不保留。
- 题图继续由现有确定性 SVG 绘制，面积比精确为4:2:1:1。生成图片的块宽不作为数学比例依据，时间标签也由实际片段时间渲染，不照搬图中重复起点。
- 教学对象来自已确认证据，不能在教学安排中任意改为其他学生。图稿中的字段长度计数仅作布局参考，输入限制沿用实际模型。
- 三道练习各自检查后才可确认，确认后才可采用；生成的文字仍是待核验草稿。未补齐准备方式、备选安排和保留内容时不可确认安排。
- 学生与家长仅读取本人或绑定学生的有效已发布内容。管理者只读授权汇总，不增加班级、权限或系统管理功能；统计显示还须保留分子、分母和时间口径。
- 发布纠错图是已应用修正后的失效状态，不再提供重复应用按钮。时间轴日期为图稿占位，实际页面使用操作记录；不能自动恢复原报告。
- 桌面三栏在窄屏改为顺序阅读或切换面板，保留原话定位、可见焦点与错误提示。详细响应式和键盘行为仍需实现后实测。

## 尚待确认

- [x] 用户选择 A 的时间线居中方向。
- [ ] 用户确认本组调整稿及关键页面布局，或提出具体修改。
- [ ] 完整前端按确认参考实现并进行交互与可访问性验证。

选图不等于用户已体验真实核验、纠错与发布操作。真实语音服务联调条件仍按任务11单独保留。

## 实际生成提示词

以下逐字保存工具输入。A第二版是工作台编辑对象，也是其他页面的风格参考；未使用命令行备用生成方式。

### workbench

```text
Edit target: the attached A teacher-workbench screenshot. Preserve its light cool-gray surfaces, blue accent, navigation rail, three-column proportions and central audio timeline. Create a refined high-fidelity Chinese product mockup for final review, landscape. Keep product “课堂学习支持”, left question context, central transcript/playback, right teacher review. Correct the diagram precisely: ONE rectangle with four equal-height parts, internal divider positions at 50%, 75%, 87.5% of total width. Label 甲乙丙丁 centered. 甲 is as wide as all three other pieces combined; 乙 as wide as 丙丁 combined. Add small accurate text “面积比 4:2:1:1（示意）”. Question remains “把一个长方形分成四块，每块都一定是四分之一吗？” Selected transcript remains “分成了四块，所以我觉得每一块都是四分之一。” Show 00:12—00:18 selected time. Simplify other transcript rows to just three short synthetic classroom statements instead of repetitive invented dialogue. Each row must have its own time. Top source badge “模拟资料” and status “真实语音服务未连接”. Right independent fields “文字核验”“身份核验”“题目核验”, each “已确认”, linked “学生甲”“题目一”; their dropdown can visibly indicate “已确认”. Separate section “学习证据 · 待确认” containing quote, explanation “需核实是否比较各块面积。” and limitation “单次回答不足以判断稳定掌握。”. Change evidence buttons to “确认学习证据”, “编辑证据”, “驳回证据”; do NOT use “无法判断” as evidence rejection. Unable-to-judge is only an available utterance review choice. Disabled downstream “生成练习” with “确认有效证据后可生成”. Sidebar “课堂”“核验工作台”“教学支持”“发布反馈”. Crisp readable Simplified Chinese, sober refined real product typography, white space, no fake mastery score, no rankings, no new logo or marketing decoration. Straight-on full screenshot, not monitor photo.
```

### teaching

```text
Use case ui-mockup. The input image is a STYLE REFERENCE only. Create a new high-fidelity desktop screen of the SAME “课堂学习支持” product, same blue/light-gray visual system, rail and typography, landscape wide. Active nav “教学支持”; other nav “课堂”“核验工作台”“发布反馈”. Header “分数的初步认识” with “模拟资料”. Breadcrumb “已确认证据 → 教学支持”. Slim left context pane with quoted synthetic original statement “我只数了四块，没有比较每块面积。”, badge “证据已确认”, small “查看原发言” link; do not invent real data or learners. Broad middle panel with tabs “分层练习”“提问安排”“下一课调整”. Active “分层练习”, three level tabs “概念巩固”“解释表达”“情境迁移”. Show one selected concept exercise editable form: question “同一个整体分成四块，是否每块都一定是四分之一？”, answer “不一定，必须比较各块面积。”, explanation “平均分成四份时，每份才都占整体的四分之一。”. Checkbox “已核对本题题干、答案与解释”. Bottom buttons “保存待核验草稿”“确认练习”; separate unselected “采用已确认练习”. Original model text collapsed “查看原始模型初稿”. Right pane “提问与下一课安排” with target “学生甲”, clearly labeled concise fields “课堂提问”“准备方式”“备选安排”“保留内容”“调整活动”“检查方法”. Show prepared teaching question about area, blank preparation with amber “待教师补充”, next-class fields as short empty inputs, disabled “确认教学安排”, no misleading ready state. A small link “查看采用与后续记录”. Use sparse legible text, realistic form affordances, deliberate grid, no performance percentages or automatic confirmed model output. This is a reference screenshot, not implementation or new feature specification.
```

### roles

```text
Use case ui-mockup. Input image is STYLE REFERENCE only. Create a clean presentation board of THREE companion product screens in the same “课堂学习支持” blue/white/light-gray design system, landscape 16:10. Label each preview clearly at top “学生端”“家长端”“管理者端”. These are separate role-specific screens, not one user's app exposing all roles. First two narrow mobile-style screens, third a wider desktop panel. Synthetic adult teaching demonstration, no faces or personal real data. Student screen: title “我的学习反馈”, badge “教师已发布”, feedback “先比较面积，再判断每块是否都是四分之一。”, three exercise level tabs “概念巩固”“解释表达”“情境迁移”, one question “分成四块就一定是平均分吗？”, expandable “查看答案与解释”, feedback input “我的疑问”, buttons “提交反馈”“申请核对记录”. Parent screen: title “孩子的学习反馈”, badge “教师已发布”, summary “本次回答需要进一步核对面积比较的依据。”, section “家庭活动” text “用同样大小的纸，比较等分与不等分。”, question field “向教师提问”, button “提交疑问”, response area “教师回复”. No audio, waveform, private teacher notes or internal job identifiers in these two screens. Admin screen: heading “教学支持汇总”, scope “授权课堂 · 当前有效状态”, compact table columns “类型”“生成”“确认”“采用”, rows “教学安排 1 1 1”“证据驱动练习 1 1 1”, a small resources section “教学活动材料 1”“练习材料 1”, clear neutral panel “有效证据涉及学生少于5人，学生相关指标已隐藏。”. NO individual student names, list, scores, rankings, mastery rate or invented analytics. Each screen has a subtle “模拟资料” badge. High-fidelity readable Simplified Chinese, consistent blue actions, clean form spacing, no decorative illustrations, no neon gradients, no code or monitor hardware.
```

### teaching修订

```text
Edit ONLY these controls in this teaching-support screenshot; preserve the rest of its A blue three-column style and all text/layout. In right panel make “教学对象：学生甲” a STATIC READ-ONLY label, remove the dropdown arrow, add small note “来自已确认证据”. In center bottom make “确认练习” disabled gray with small note “三题均核对后可确认”; make “采用已确认练习” disabled gray because these exercises are still a draft. Keep “保存待核验草稿” usable in blue outline. Do not invent new controls or change the source quote. Add subtle badge “待核验草稿” to the exercise heading. Keep overall typography and whitespace identical.
```

### roles修订

```text
Edit this THREE-role reference board with just these corrections, preserve A blue-white styling and all remaining content. In management screen remove EVERY sidebar item except “教学支持汇总”; no 首页, no 教学活动材料/练习材料 navigation, no 班级与权限, no 系统设置. It is a read-only authorized summary, no permissions management. Keep resource counts inside the content but remove chevrons suggesting drilldown. In STUDENT screen remove the colored rectangle diagram completely; use instead short plain text example “四块面积：1/2、1/4、1/8、1/8” under the question. Do not add a new chart or diagram. Keep all role separation, parent-only home activity, student feedback controls and sample privacy message. No other changes, no new product functions.
```

### 发布纠错

```text
Use case ui-mockup. The input image is only STYLE REFERENCE for the selected A blue/light-gray “课堂学习支持” design. Generate a new landscape high-fidelity desktop screen, same navigation rail, crisp Simplified Chinese, restrained blue primary buttons, generous whitespace. Active nav “发布反馈”; other nav “课堂”“核验工作台”“教学支持”. Top “分数的初步认识”, small “模拟资料”. This screen demonstrates correction ALREADY APPLIED and old reports stopped. Left broad pane header “发布与接收预览”, tabs “学生反馈”“家长摘要”, active student tab. Static recipient label “原报告接收对象：学生甲”. Amber status “依据已变化 · 等待新版”. Center large empty-safe state: “旧报告正文已停止提供”, secondary text “原发言归属已修正，请重新核验后发布新版。”, no old private report body shown. Below chronological three short event lines “原报告已发布”“教师修正学生归属”“旧报告已失效”, and disabled button “重核后发布新版”. Right pane “纠错与关联影响”, notice “归属已由学生甲改为学生乙”, list “学习证据 1 条”“练习 1 组”“教学安排 1 项”“学生报告 1 份”“家长报告 1 份”, all tagged “已失效”. Separate neutral box “人工编辑和检查记录已保留”. Bottom clear small warning “已下载的离线副本不能远程收回。” Primary button “返回发言重新核验”, secondary “查看纠错记录”. Do not show a second apply button after correction is already applied, do not claim automatic regeneration or automatically published new reports. No API IDs, version hashes, logs, real student data, mastery score, remote delete success or new product functions. A calm realistic teacher decision screen, not a poster.
```

