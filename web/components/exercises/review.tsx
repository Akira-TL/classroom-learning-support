"use client";

import { useState } from "react";
import { evidenceNames } from "../../lib/evidence";
import { exercisesApi, exercisesSchema, levelNames } from "../../lib/exercises";
import type { Exercise, ExerciseRecord } from "../../lib/exercises";
import "../presentation/role-panels.css";

export function ExerciseReview({ classroomId, record, onSaved }: {
  classroomId: string; record: ExerciseRecord; onSaved: (record: ExerciseRecord) => void;
}) {
  const [items, setItems] = useState(record.exercises);
  const [revision, setRevision] = useState(record.revision);
  const [checked, setChecked] = useState<Exercise["level"][]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [activeLevel, setActiveLevel] = useState<Exercise["level"]>("concept");
  const dirty = JSON.stringify(items) !== JSON.stringify(record.exercises);
  const stale = record.status === "stale";

  function accept(updated: ExerciseRecord) {
    setItems(updated.exercises); setRevision(updated.revision); onSaved(updated);
    setNotice(`练习已更新，版本 ${updated.revision}。`);
  }
  function edit(index: number, content: Partial<Exercise>) {
    const level = items[index].level;
    setItems((previous) => previous.map((item, position) => position === index ? { ...item, ...content } : item));
    setChecked((previous) => previous.filter((item) => item !== level));
  }
  async function act(action: "pending" | "confirmed" | "rejected" | "adopt" | "unadopt") {
    setError(""); setNotice("");
    const parsed = exercisesSchema.safeParse(items);
    if (!parsed.success) {
      setError(parsed.error.issues.map((issue) => `${issue.path.join(".")}：${issue.message}`).join("；"));
      return;
    }
    setBusy(true);
    try {
      const updated = action === "adopt" || action === "unadopt"
        ? await exercisesApi.adopt(classroomId, record.id, revision, action === "adopt")
        : await exercisesApi.review(classroomId, record.id, revision, action, parsed.data);
      accept(updated);
      if (action === "pending" || action === "rejected") setChecked([]);
      if (action === "pending") setNotice(`待核验草稿已保存，版本 ${updated.revision}；未确认且未采用。`);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "练习操作失败。"); }
    finally { setBusy(false); }
  }

  return <section className="exercise-review" aria-label="分层练习核验">
    <header className="review-meta"><div className="badge-group">
      <span className={`status-badge status-${record.status}`}>{evidenceNames[record.status]}</span>
      <span className="status-badge">{record.adopted ? "已采用" : "未采用"}</span></div>
      <span className="basis-label">证据版本 {record.evidence_revision} · 练习版本 {record.revision}</span></header>
    {error && <p role="alert">{error} 发生版本冲突时请刷新并检查后手动载入，不自动覆盖。</p>}
    {revision !== record.revision && <p role="alert">记录已更新，当前编辑保留；请刷新后决定是否载入最新内容。</p>}
    {stale && <p>依据过期，练习不能继续确认或采用。请重核证据后明确重新生成。</p>}
    <p role="status">{notice}</p>
    <fieldset className="review-fields" disabled={busy || stale}>
      <legend className="sr-only">逐题编辑与核对，模型初稿须教师逐题核验</legend>
      <div className="level-switch" role="group" aria-label="选择练习层次">
        {items.map((item) => <button key={item.level} aria-pressed={activeLevel === item.level}
          onClick={() => setActiveLevel(item.level)}>{levelNames[item.level]}{checked.includes(item.level) ? " ✓" : ""}
        </button>)}
      </div>
      {items.map((item, index) => <fieldset className="exercise-editor" key={item.level}
        hidden={activeLevel !== item.level}>
        <legend>{levelNames[item.level]}</legend>
        <label>题干<textarea maxLength={2000} value={item.question}
          onChange={(event) => edit(index, { question: event.target.value })} /></label>
        <label>答案<textarea maxLength={2000} value={item.answer}
          onChange={(event) => edit(index, { answer: event.target.value })} /></label>
        <label>解释<textarea maxLength={3000} value={item.explanation}
          onChange={(event) => edit(index, { explanation: event.target.value })} /></label>
        <label><input type="checkbox" checked={checked.includes(item.level)} onChange={(event) => {
          setChecked((previous) => event.target.checked ? [...previous, item.level]
            : previous.filter((level) => level !== item.level));
        }} />我已核对本题题干、答案与解释</label>
      </fieldset>)}
      <div className="action-row">
      <button onClick={() => void act("pending")}>保存待核验草稿</button>
      <button className="primary-button" disabled={checked.length !== 3}
        onClick={() => void act("confirmed")}>确认练习</button>
      <button className="danger-text" onClick={() => void act("rejected")}>驳回练习</button>
      </div><p className="check-progress">已核对 {checked.length}/3 题 · 三题均核对后可确认</p>
      <div className="adoption-row"><span>课堂使用</span>
      <button disabled={record.status !== "confirmed" || dirty || revision !== record.revision || record.adopted}
        onClick={() => void act("adopt")}>采用已确认练习</button>
      <button disabled={!record.adopted || dirty || revision !== record.revision}
        onClick={() => void act("unadopt")}>撤销采用</button>
      </div>
      {dirty && <p>当前编辑尚未保存，可先保存待核验草稿；逐题核对并确认后才能采用。</p>}
      <button className="quiet-button" onClick={() => {
        setItems(record.exercises); setRevision(record.revision); setChecked([]); setError("");
        setNotice("已载入当前记录，未保存的编辑已重置。");
      }}>载入最新练习并重置编辑</button>
    </fieldset>
    <details className="audit-details"><summary>查看原始模型初稿</summary>
      <p>模型：{record.original.model}。原稿独立保留，不随教师编辑覆盖。</p>
      {record.original.content.exercises.map((item) => <div key={item.level}><h5>{levelNames[item.level]}</h5>
        <p>{item.question}</p><p>答案：{item.answer}</p><p>解释：{item.explanation}</p></div>)}
    </details>
    <details className="audit-details"><summary>查看依据与核验记录</summary>
      <p>依据证据 {record.evidence_id}，版本 {record.evidence_revision}；
        练习版本 {record.revision}，当前编辑依据版本 {revision}；核验人 {record.reviewed_by ?? "尚无记录"}。</p>
    </details>
  </section>;
}
