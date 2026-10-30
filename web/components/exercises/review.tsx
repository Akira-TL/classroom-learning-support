"use client";

import { useState } from "react";
import { evidenceNames } from "../../lib/evidence";
import { exercisesApi, exercisesSchema, levelNames } from "../../lib/exercises";
import type { Exercise, ExerciseRecord } from "../../lib/exercises";

export function ExerciseReview({ classroomId, record, onSaved }: {
  classroomId: string; record: ExerciseRecord; onSaved: (record: ExerciseRecord) => void;
}) {
  const [items, setItems] = useState(record.exercises);
  const [revision, setRevision] = useState(record.revision);
  const [checked, setChecked] = useState<Exercise["level"][]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
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
  async function act(action: "confirmed" | "rejected" | "adopt" | "unadopt") {
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
    } catch (failure) { setError(failure instanceof Error ? failure.message : "练习操作失败。"); }
    finally { setBusy(false); }
  }

  return <section aria-label="分层练习核验">
    <h6>练习：{evidenceNames[record.status]}；{record.adopted ? "已采用" : "未采用"}</h6>
    <p>依据证据 {record.evidence_id}，版本 {record.evidence_revision}；
      练习版本 {record.revision}，当前编辑依据版本 {revision}；核验人 {record.reviewed_by ?? "未核验"}。</p>
    <p>模型输出没有经过自动数学正确性认证。请逐题检查题干、图形需求、答案与解释。</p>
    {error && <p role="alert">{error} 发生版本冲突时请刷新并检查后手动载入，不自动覆盖。</p>}
    {revision !== record.revision && <p role="alert">记录已更新，当前编辑保留；请刷新后决定是否载入最新内容。</p>}
    {stale && <p>依据过期，练习不能继续确认或采用。请重核证据后明确重新生成。</p>}
    <p role="status">{notice}</p>
    <fieldset disabled={busy || stale}>
      <legend>逐题编辑与核对</legend>
      {items.map((item, index) => <fieldset key={item.level}>
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
      <button disabled={checked.length !== 3} onClick={() => void act("confirmed")}>确认这组练习</button>
      <button onClick={() => void act("rejected")}>驳回这组练习</button>
      <button disabled={record.status !== "confirmed" || dirty || revision !== record.revision || record.adopted}
        onClick={() => void act("adopt")}>采用已确认练习</button>
      <button disabled={!record.adopted || dirty || revision !== record.revision}
        onClick={() => void act("unadopt")}>撤销采用</button>
      {dirty && <p>当前编辑尚未保存，请先逐题核对并确认，再操作采用。</p>}
      <button onClick={() => {
        setItems(record.exercises); setRevision(record.revision); setChecked([]); setError("");
        setNotice("已载入当前记录，未保存的编辑已重置。");
      }}>载入最新练习并重置编辑</button>
    </fieldset>
  </section>;
}
