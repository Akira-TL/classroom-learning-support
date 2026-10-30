"use client";

import { useState } from "react";
import { evidenceApi, evidenceContentSchema, evidenceNames } from "../lib/evidence";
import type { EvidenceAction, EvidenceRecord } from "../lib/evidence";

export function EvidenceReview({ classroomId, record, onSaved }: {
  classroomId: string; record: EvidenceRecord; onSaved: (updated: EvidenceRecord) => void;
}) {
  const [content, setContent] = useState(record.content);
  const [revision, setRevision] = useState(record.revision);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

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
    <h5>证据：{evidenceNames[record.status]}</h5>
    <p>证据版本 {record.revision}；本次编辑依据版本 {revision}；核验人 {record.reviewed_by ?? "未核验"}</p>
    <p>依据：题目 {record.basis.context.question_id}；发言 {record.basis.segment_id}；
      发言版本 {record.basis.utterance_version}；题目版本指纹 {record.basis.question_fingerprint}</p>
    <p>模型：{record.original.model}</p>
    <blockquote>引用原话：{record.content.quote}</blockquote>
    {record.revision !== revision && <p role="alert">记录已有更新，当前编辑保留；请刷新检查后载入最新内容。</p>}
    {record.status === "stale" && <p>过期证据保留供核对，不能继续确认。请重核发言并明确重新生成。</p>}
    {error && <p role="alert">{error} 版本冲突不会自动重试覆盖，请刷新后重新检查。</p>}
    <p role="status">{notice}</p>
    <fieldset disabled={busy || record.status === "stale"}>
      <legend>教师编辑与判断（原话引用不可修改）</legend>
      <label>解释<textarea value={content.interpretation} maxLength={3000}
        onChange={(event) => setContent({ ...content, interpretation: event.target.value })} /></label>
      <label>局限<textarea value={content.limitation} maxLength={2000}
        onChange={(event) => setContent({ ...content, limitation: event.target.value })} /></label>
      <label>跟进问题<textarea value={content.follow_up_question} maxLength={1000}
        onChange={(event) => setContent({ ...content, follow_up_question: event.target.value })} /></label>
      <button disabled={busy} onClick={() => void review("confirmed")}>确认此证据</button>
      <button disabled={busy} onClick={() => void review("rejected")}>驳回此证据</button>
      <button disabled={busy} onClick={() => {
        setContent(record.content); setRevision(record.revision); setError("");
        setNotice("已载入页面当前记录，未保存的编辑已重置。");
      }}>载入最新内容并重置编辑</button>
    </fieldset>
  </section>;
}
