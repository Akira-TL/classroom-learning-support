"use client";

import { AudioPanel } from "./audio-panel";

import { useState } from "react";
import type { FormEvent } from "react";
import type { Classroom } from "../lib/types";
import { reviewNames, reviewStateSchema, speech } from "../lib/speech";
import type { ReviewRequest, ReviewState, Utterance } from "../lib/speech";
import styles from "./workspace/workspace.module.css";

const labels = ["pending", "confirmed", "unable"] as const;
function initial(item: Utterance): ReviewRequest {
  return {
    expected_version: item.version, teacher_text: item.teacher_text,
    student_alias: item.student_alias, question_id: item.question_id,
    text_review: item.text_review, identity_review: item.identity_review, question_review: item.question_review,
  };
}
function ReviewSelect({ label, value, onChange }: {
  label: string; value: ReviewState; onChange: (value: ReviewState) => void;
}) {
  return <label className={styles.reviewStatus}><span>{label}</span><select value={value}
    onChange={(event) => onChange(reviewStateSchema.parse(event.target.value))}>
    {labels.map((key) => <option key={key} value={key}>{reviewNames[key]}</option>)}
  </select></label>;
}

export function UtteranceReview({ classroom, utterance, onSaved, showAudio = true }: {
  classroom: Classroom; utterance: Utterance; onSaved: () => Promise<void>; showAudio?: boolean;
}) {
  const [draft, setDraft] = useState(() => initial(utterance));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const stale = draft.expected_version !== utterance.version;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const updated = await speech.review(classroom.id, utterance, draft);
      setDraft(initial(updated));
      setNotice(`核验已保存，应用版本 ${updated.version}。`);
      await onSaved();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "核验保存失败，请刷新后重新检查。");
    } finally { setBusy(false); }
  }

  return <form onSubmit={save} className={`${styles.card} ${styles.reviewCard}`}>
    <div className={styles.cardHeading}><h2>教师核验</h2><span className={styles.count}>三项独立</span></div>
    {error && <p role="alert">{error} 发生版本冲突时请先刷新时间线；不会自动重试覆盖。</p>}
    {stale && <p role="alert">发言已有较新版本，当前编辑保留。请检查原话，再决定是否载入最新记录。</p>}
    <p role="status">{notice}</p>
    <fieldset disabled={busy} className={styles.compactFieldset}>
      <legend className={styles.srOnly}>分别核验，本次编辑依据应用版本 {draft.expected_version}</legend>
      {showAudio && <AudioPanel classroomId={classroom.id} utterance={utterance} onSaved={onSaved} />}
      {utterance.phase === "partial" || utterance.phase === "withdraw"
        ? <p>临时或已撤回发言不能确认，可记录待核验或无法判断。</p> : null}
      <div className={styles.compactRows}>
      <div className={styles.compactRow}>
      <ReviewSelect label="文字核验" value={draft.text_review}
        onChange={(text_review) => setDraft({ ...draft, text_review })} />
      <span className={styles.muted}>仅判断文本内容</span>
      </div>
      <div className={styles.compactRow}>
      <ReviewSelect label="身份核验" value={draft.identity_review}
        onChange={(identity_review) => setDraft({ ...draft, identity_review })} />
      <label className={styles.association}><span className={styles.srOnly}>学生归属</span>
        <select value={draft.student_alias ?? ""}
        onChange={(event) => setDraft({ ...draft, student_alias: event.target.value || null })}>
        <option value="">尚未关联</option>
        {classroom.students.map((id) => <option key={id} value={id}>{id}</option>)}
      </select></label>
      </div>
      <div className={styles.compactRow}>
      <ReviewSelect label="题目核验" value={draft.question_review}
        onChange={(question_review) => setDraft({ ...draft, question_review })} />
      <label className={styles.association}><span className={styles.srOnly}>关联题目</span>
        <select value={draft.question_id ?? ""}
        onChange={(event) => setDraft({ ...draft, question_id: event.target.value || null })}>
        <option value="">尚未关联</option>
        {classroom.questions.map((item, index) => <option key={item.id} value={item.id}>
          题目 {index + 1} · {item.id}
        </option>)}
      </select></label>
      </div>
      </div>
      <details className={styles.compactDetails}><summary>
        修订文字与版本{draft.teacher_text ? "（有修订文字）" : ""}
      </summary>
      <label>教师修订文字<textarea value={draft.teacher_text ?? ""} maxLength={6000}
        placeholder="留空则保留上游原文，不代表已确认"
        onChange={(event) => setDraft({ ...draft, teacher_text: event.target.value || null })} /></label>
      <p className={styles.muted}>编辑依据发言版本 {draft.expected_version}；当前版本 {utterance.version}。</p>
      <button type="button" onClick={() => {
        setDraft(initial(utterance)); setError(""); setNotice("已载入页面当前记录，尚未保存的编辑已重置。");
      }}>载入最新记录并重置编辑</button>
      </details>
      <div className={styles.actions}>
      <button type="submit" disabled={stale}>{busy ? "正在保存…" : "保存分别核验结果"}</button>
      </div>
    </fieldset>
  </form>;
}
