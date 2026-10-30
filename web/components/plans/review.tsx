"use client";

import { useState } from "react";
import { evidenceNames } from "../../lib/evidence";
import { planComplete, planContentSchema, plansApi } from "../../lib/plans";
import type { PlanRecord } from "../../lib/plans";

const fields = [
  { key: "question", label: "课堂提问（模型初填，可修改）", max: 2000 },
  { key: "preparation", label: "准备方式（教师补充）", max: 2000 },
  { key: "alternative", label: "备选安排（教师补充）", max: 2000 },
  { key: "keep_content", label: "下一课保留内容（教师补充）", max: 3000 },
  { key: "activity", label: "调整活动（模型初填，可修改）", max: 3000 },
  { key: "check_method", label: "检查方法（模型初填，可修改）", max: 2000 },
] as const;

export function PlanReview({ classroomId, record, onSaved }: {
  classroomId: string; record: PlanRecord; onSaved: (updated: PlanRecord) => void;
}) {
  const [content, setContent] = useState(record.content);
  const [revision, setRevision] = useState(record.revision);
  const [observation, setObservation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const dirty = JSON.stringify(content) !== JSON.stringify(record.content);
  const changed = revision !== record.revision;
  const stale = record.status === "stale";

  async function act(action: "confirmed" | "rejected" | "adopt" | "unadopt" | "observe") {
    setError(""); setNotice("");
    const parsed = planContentSchema.safeParse(content);
    if (!parsed.success) {
      setError(parsed.error.issues.map((issue) => `${issue.path.join(".")}：${issue.message}`).join("；"));
      return;
    }
    setBusy(true);
    try {
      const updated = action === "confirmed" || action === "rejected"
        ? await plansApi.review(classroomId, record.id, revision, action, parsed.data)
        : await plansApi.adopt(classroomId, record.id, revision,
          action === "observe" ? record.adopted : action === "adopt", observation.trim() || null);
      setContent(updated.content); setRevision(updated.revision); setObservation(""); onSaved(updated);
      setNotice(`教学安排已更新，版本 ${updated.revision}。`);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "教学安排操作失败。"); }
    finally { setBusy(false); }
  }

  return <section aria-label="提问与下一课安排核验">
    <h6>教学安排：{evidenceNames[record.status]}；{record.adopted ? "已采用" : "未采用"}</h6>
    <p>依据证据 {record.evidence_id}，版本 {record.evidence_revision}；安排版本 {record.revision}；
      本次编辑依据版本 {revision}；核验人 {record.reviewed_by ?? "未核验"}。</p>
    <p>提问对象：{record.content.target_student}。对象来自已确认证据，不能在此改成其他学生。</p>
    <details><summary>原始模型返回（保留，不随教师编辑覆盖）</summary>
      <p>模型：{record.original.model}</p>
      <p>课堂提问：{record.original.content.classroom_question}</p>
      <p>下一课调整：{record.original.content.next_lesson}</p>
      <p>检查方法：{record.original.content.check_method}</p>
    </details>
    {error && <p role="alert">{error} 版本冲突不会自动重试，请刷新后检查并手动载入。</p>}
    {changed && <p role="alert">记录已有新版本，当前编辑保留，请检查后再决定载入。</p>}
    {stale && <p>依据已失效，此安排不能继续确认或采用，需重核证据后明确重新生成。</p>}
    <p role="status">{notice}</p>
    <fieldset disabled={busy || stale}>
      <legend>教师编辑教学安排</legend>
      {fields.map((field) => <label key={field.key}>{field.label}
        <textarea maxLength={field.max} value={content[field.key]}
          onChange={(event) => setContent({ ...content, [field.key]: event.target.value })} />
      </label>)}
      {!planComplete(content) && <p>准备方式、备选安排和下一课保留内容尚待教师补齐，当前不能确认或采用。</p>}
      <button disabled={!planComplete(content)} onClick={() => void act("confirmed")}>确认教学安排</button>
      <button onClick={() => void act("rejected")}>驳回教学安排</button>
      <button disabled={dirty || changed || !planComplete(content) || record.status !== "confirmed" || record.adopted}
        onClick={() => void act("adopt")}>采用已确认安排</button>
      <button disabled={dirty || changed || !record.adopted} onClick={() => void act("unadopt")}>撤销采用</button>
      {dirty && <p>编辑尚未保存；请先确认后再改变采用状态或记录检查结果。</p>}
      <label>后续检查结果<textarea maxLength={3000} value={observation}
        onChange={(event) => setObservation(event.target.value)} /></label>
      <button disabled={dirty || changed || !observation.trim()}
        onClick={() => void act("observe")}>保存检查结果（维持当前采用状态）</button>
      <button onClick={() => {
        setContent(record.content); setRevision(record.revision); setError("");
        setNotice("已载入页面当前记录，未保存的教学安排编辑已重置，检查结果草稿保留。");
      }}>载入最新安排并重置编辑</button>
    </fieldset>
    <h6>后续检查记录</h6>
    {record.observations.length === 0 && <p>尚无检查结果。</p>}
    <ul>{record.observations.map((item, index) => <li key={`${item.revision}/${index}`}>
      {item.text}（记录人 {item.teacher}，安排版本 {item.revision}）
    </li>)}</ul>
  </section>;
}
