"use client";

import { useEffect, useState } from "react";
import { correctionsApi } from "../../lib/corrections/api";
import type { Correction, CorrectionApply, CorrectionAssessment } from "../../lib/corrections/api";
import type { Classroom } from "../../lib/types";
import { reviewNames, reviewStateSchema } from "../../lib/speech";
import type { Utterance } from "../../lib/speech";

function initial(utterance: Utterance): Correction {
  return {
    session_id: utterance.session_id, segment_id: utterance.segment_id,
    review: {
      expected_version: utterance.version, teacher_text: utterance.teacher_text ?? utterance.upstream_text,
      student_alias: utterance.student_alias, question_id: utterance.question_id,
      text_review: "pending", identity_review: "pending", question_review: "pending",
    },
  };
}
const reviewFields = [
  ["text_review", "文字核验"], ["identity_review", "身份核验"], ["question_review", "题目核验"],
] as const;

export function CorrectionPanel({ classroom, utterance, onSaved }: {
  classroom: Classroom; utterance: Utterance; onSaved: () => Promise<void>;
}) {
  const [draft, setDraft] = useState(() => initial(utterance));
  const [draftClassroom, setDraftClassroom] = useState(classroom.id);
  const [preview, setPreview] = useState<CorrectionAssessment | null>(null);
  const [attempt, setAttempt] = useState<CorrectionApply | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const stale = draftClassroom !== classroom.id || draft.review.expected_version !== utterance.version
    || draft.session_id !== utterance.session_id || draft.segment_id !== utterance.segment_id;

  useEffect(() => {
    setPreview(null); setAttempt(null);
  }, [classroom.id, utterance.session_id, utterance.segment_id, utterance.version]);

  function change(review: Correction["review"]) {
    setDraft({ ...draft, review }); setPreview(null); setAttempt(null); setNotice("");
  }

  async function assess() {
    setBusy(true); setError(""); setNotice(""); setPreview(null);
    try { setPreview(await correctionsApi.preview(classroom.id, draft)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "影响预览失败。"); }
    finally { setBusy(false); }
  }

  async function apply() {
    if (!preview || stale) return;
    const body = attempt ?? { ...draft, idempotency_key: crypto.randomUUID() };
    setAttempt(body); setBusy(true); setError(""); setNotice("");
    try {
      const result = await correctionsApi.apply(classroom.id, body);
      setPreview(null); setAttempt(null); setDraft(initial(result.utterance));
      setNotice(`修正已保存为发言版本 ${result.utterance.version}，相关旧内容已失效。请重新核验后再生成和发布。`);
      try { await onSaved(); }
      catch { setError("修正已成功，但页面刷新失败；请手动刷新发言与相关结果。"); }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "未确认修正成功，可重试同一次请求。");
    } finally { setBusy(false); }
  }

  async function refresh() {
    setBusy(true);
    try { await onSaved(); setNotice("已刷新来源，当前编辑保留；可比较后手动载入最新记录。"); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "刷新失败。"); }
    finally { setBusy(false); }
  }

  return <section aria-label="纠错影响与关联更新">
    <h4>修正事实并检查关联影响</h4>
    <p>三项核验默认待核验；请分别作出判断。修正不会自动重新生成建议或发布报告。</p>
    {error && <p role="alert">{error} 若发生版本冲突，请先刷新并比较；编辑不会自动覆盖新记录。</p>}
    {stale && <p role="alert">来源已变化，当前编辑保留；载入最新记录前不能应用。</p>}
    <p role="status">{notice}</p>
    <fieldset disabled={busy}>
      <legend>编辑依据：发言版本 {draft.review.expected_version}</legend>
      <label>修正文字<textarea maxLength={6000} value={draft.review.teacher_text ?? ""}
        onChange={(event) => change({ ...draft.review, teacher_text: event.target.value || null })} /></label>
      <label>学生归属<select value={draft.review.student_alias ?? ""}
        onChange={(event) => change({ ...draft.review, student_alias: event.target.value || null })}>
        <option value="">尚不能确定</option>
        {classroom.students.map((id) => <option value={id} key={id}>{id}</option>)}
      </select></label>
      <label>关联题目<select value={draft.review.question_id ?? ""}
        onChange={(event) => change({ ...draft.review, question_id: event.target.value || null })}>
        <option value="">尚未关联</option>
        {classroom.questions.map((item) => <option value={item.id} key={item.id}>{item.id}：{item.text}</option>)}
      </select></label>
      {reviewFields.map(([key, label]) => <label key={key}>{label}<select value={draft.review[key]}
        onChange={(event) => change({ ...draft.review, [key]: reviewStateSchema.parse(event.target.value) })}>
        {reviewStateSchema.options.map((value) => <option key={value} value={value}>{reviewNames[value]}</option>)}
      </select></label>)}
      <button type="button" disabled={stale} onClick={() => void assess()}>预览受影响内容</button>
      {preview && <article>
        <p>预览不会修改事实。应用后以下内容需重新核验：</p>
        <ul>
          <li>学习证据 {preview.impact.counts.evidence} 条：{preview.impact.evidence_ids.join("、") || "无"}</li>
          <li>练习 {preview.impact.counts.exercises} 组：{preview.impact.exercise_ids.join("、") || "无"}</li>
          <li>教学安排 {preview.impact.counts.plans} 项：{preview.impact.plan_ids.join("、") || "无"}</li>
          <li>学生报告 {preview.impact.counts.student_reports} 份：{preview.impact.student_report_ids.join("、") || "无"}</li>
          <li>家长报告 {preview.impact.counts.parent_reports} 份：{preview.impact.parent_report_ids.join("、") || "无"}</li>
        </ul>
        <p>已发布旧内容将停止提供；人工编辑和观察记录保留。最终影响范围由应用事务重新核对。</p>
        <button type="button" disabled={stale} onClick={() => void apply()}>
          {attempt ? "重试同一次修正请求" : "确认影响并应用修正"}
        </button>
      </article>}
      <button type="button" onClick={() => void refresh()}>刷新发言并保留编辑</button>
      <button type="button" onClick={() => {
        setDraft(initial(utterance)); setDraftClassroom(classroom.id);
        setPreview(null); setAttempt(null); setError("");
        setNotice("已载入页面最新事实，未保存编辑已重置；请重新分别核验。");
      }}>载入页面最新事实并重置编辑</button>
    </fieldset>
  </section>;
}
