"use client";

import { useId, useState } from "react";
import { evidenceApi, evidenceContentSchema, evidenceNames } from "../lib/evidence";
import type { EvidenceAction, EvidenceRecord } from "../lib/evidence";
import styles from "./workspace/workspace.module.css";

export function EvidenceReview({ classroomId, record, onSaved }: {
  classroomId: string; record: EvidenceRecord; onSaved: (updated: EvidenceRecord) => void;
}) {
  const [content, setContent] = useState(record.content);
  const [revision, setRevision] = useState(record.revision);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState(false);
  const editorId = useId();
  const changed = JSON.stringify(content) !== JSON.stringify(record.content);
  const disabled = busy || record.status === "stale" || record.revision !== revision;

  async function review(action: EvidenceAction) {
    const validated = evidenceContentSchema.safeParse(content);
    if (!validated.success) {
      setError(validated.error.issues.map((issue) => `${issue.path.join(".")}：${issue.message}`).join("；"));
      return;
    }
    setBusy(true); setError(""); setNotice("");
    try {
      const updated = await evidenceApi.review(classroomId, record, revision, action, validated.data);
      setContent(updated.content); setRevision(updated.revision); onSaved(updated);
      setNotice(`核验已保存，证据版本 ${updated.revision}。`);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "证据核验失败。");
    } finally { setBusy(false); }
  }

  return <section aria-label="学习证据核验">
    <div className={styles.cardHeading}><h3>学习证据</h3>
      <span className={record.status === "confirmed" ? styles.good : styles.warning}>
        {evidenceNames[record.status]}</span></div>
    <blockquote>{record.content.quote}</blockquote>
    {changed && <p className={styles.warning}>下方为未保存编辑预览；确认时将保存本次编辑。</p>}
    <div className={styles.evidenceReading}>
      <h4>证据说明</h4><p>{content.interpretation}</p>
      <h4>核验限制</h4><p>{content.limitation}</p>
    </div>
    {record.revision !== revision && <p role="alert">记录已有更新，当前编辑保留；请刷新检查后载入最新内容。</p>}
    {record.status === "stale" && <p>过期证据保留供核对，不能继续确认。请重核发言并明确重新生成。</p>}
    {error && <p role="alert">{error} 版本冲突不会自动重试覆盖，请刷新后重新检查。</p>}
    <p role="status">{notice}</p>
    <details id={editorId} open={editing} className={styles.evidenceEditor}
      onToggle={(event) => setEditing(event.currentTarget.open)}>
    <summary>编辑证据说明、限制与跟进问题</summary>
    <fieldset disabled={busy || record.status === "stale"}>
      <legend>教师编辑与判断（原话引用不可修改）</legend>
      <label>证据说明<textarea value={content.interpretation} maxLength={3000}
        onChange={(event) => setContent({ ...content, interpretation: event.target.value })} /></label>
      <label>核验限制<textarea value={content.limitation} maxLength={2000}
        onChange={(event) => setContent({ ...content, limitation: event.target.value })} /></label>
      <label>跟进问题<textarea value={content.follow_up_question} maxLength={1000}
        onChange={(event) => setContent({ ...content, follow_up_question: event.target.value })} /></label>
    </fieldset>
    </details>
    <div className={styles.evidenceActions}>
      <button className={styles.primary} disabled={disabled} onClick={() => void review("confirmed")}>确认学习证据</button>
      <button disabled={busy} aria-expanded={editing} aria-controls={editorId}
        onClick={() => setEditing((value) => !value)}>编辑证据</button>
      <button data-tone="danger" disabled={disabled} onClick={() => void review("rejected")}>驳回证据</button>
    </div>
    <details className={styles.audit}><summary>依据版本与原始初稿</summary>
      <button disabled={busy} onClick={() => {
        setContent(record.content); setRevision(record.revision); setError("");
        setNotice("已载入页面当前记录，未保存的编辑已重置。");
      }}>载入最新内容并重置编辑</button>
      <p>证据版本 {record.revision}；编辑依据 {revision}；核验人 {record.reviewed_by ?? "未核验"}</p>
      <p>题目 {record.basis.context.question_id}；发言 {record.basis.segment_id}；
        发言版本 {record.basis.utterance_version}；题目指纹 {record.basis.question_fingerprint}</p>
      <p>{record.original.model === "teacher_manual" ? "来源：教师人工录入" : `模型：${record.original.model}`}</p>
      <h4>原始说明</h4><p>{record.original.content.interpretation}</p>
      <h4>原始限制</h4><p>{record.original.content.limitation}</p>
      <h4>原始跟进问题</h4><p>{record.original.content.follow_up_question}</p>
    </details>
  </section>;
}
