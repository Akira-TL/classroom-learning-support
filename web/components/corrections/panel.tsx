"use client";

import { useEffect, useState } from "react";
import { correctionsApi } from "../../lib/corrections/api";
import type { Correction, CorrectionApply, CorrectionAssessment } from "../../lib/corrections/api";
import type { Classroom } from "../../lib/types";
import { reviewNames, reviewStateSchema } from "../../lib/speech";
import type { Utterance } from "../../lib/speech";
import "../presentation/role-panels.css";

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
const impactFields = [
  ["evidence", "学习证据"], ["exercises", "练习"], ["plans", "教学安排"],
  ["student_reports", "学生报告"], ["parent_reports", "家长报告"],
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
  const [applied, setApplied] = useState<{
    classroom: string; session: string; segment: string; version: number;
    impact: CorrectionAssessment["impact"]; from: string | null; to: string | null;
  } | null>(null);
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
      setApplied({ classroom: classroom.id, session: result.utterance.session_id,
        segment: result.utterance.segment_id, version: result.utterance.version, impact: result.impact,
        from: preview.current.student_alias, to: result.utterance.student_alias });
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

  const currentApplied = applied && applied.classroom === classroom.id && applied.session === utterance.session_id
    && applied.segment === utterance.segment_id && applied.version === utterance.version ? applied : null;
  return <section className="support-panel correction-panel" aria-label="纠错影响与关联更新">
    <p className="eyebrow">发布反馈 · 事实修正</p><h4>纠错与关联影响</h4>
    <p className="panel-intro">三项核验分别判断；应用修正后需重新核验、生成并发布。</p>
    {error && <p role="alert">{error} 若发生版本冲突，请先刷新并比较；编辑不会自动覆盖新记录。</p>}
    {stale && <p role="alert">来源已变化，当前编辑保留；载入最新记录前不能应用。</p>}
    <p role="status">{notice}</p>
    {currentApplied && <section className="applied-correction" aria-label="本次修正已应用">
      <div className="feedback-highlight"><span className="status-badge status-confirmed">本次修正已应用</span>
        <h4>{currentApplied.from !== currentApplied.to
          ? `归属由 ${currentApplied.from ?? "未确定"} 改为 ${currentApplied.to ?? "未确定"}`
          : "原发言内容或核验结果已修正"}</h4><p>已保存为发言版本 {currentApplied.version}。</p></div>
      <ul className="impact-list">{impactFields.map(([key, label]) => <li key={key}>
        <span>{label}</span><strong>{currentApplied.impact.counts[key]}</strong>
        <span className="status-badge status-stale">旧依据已失效</span></li>)}</ul>
      <p className="completion-note">人工编辑和检查记录保留，请重新核验后发布新版。</p>
      <a href={`#${encodeURIComponent(`utterance-${utterance.session_id}-${utterance.segment_id}`)}`}>
        返回原发言重新核验</a>
    </section>}
    <details className="correction-editor"><summary>编辑事实并预览关联影响</summary>
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
      <button className="primary-button" type="button" disabled={stale}
        onClick={() => void assess()}>预览受影响内容</button>
      {preview && <article className="publish-preview">
        <p>预览不会修改事实。应用后以下内容需重新核验：</p>
        <ul className="impact-list">{impactFields.map(([key, label]) => <li key={key}><span>{label}</span>
          <strong>{preview.impact.counts[key]}</strong><span className="status-badge status-pending">应用后失效</span>
        </li>)}</ul>
        <details className="audit-details"><summary>查看受影响记录编号</summary>
          <p>学习证据：{preview.impact.evidence_ids.join("、") || "无"}</p>
          <p>练习：{preview.impact.exercise_ids.join("、") || "无"}</p>
          <p>教学安排：{preview.impact.plan_ids.join("、") || "无"}</p>
          <p>学生报告：{preview.impact.student_report_ids.join("、") || "无"}</p>
          <p>家长报告：{preview.impact.parent_report_ids.join("、") || "无"}</p></details>
        <p>已发布旧内容将停止提供；人工编辑和观察记录保留。最终影响范围由应用事务重新核对。</p>
        <button className="primary-button" type="button" disabled={stale} onClick={() => void apply()}>
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
    </details><p className="privacy-note">已下载的离线副本不能远程收回，请通知接收者核对新版。</p>
  </section>;
}
