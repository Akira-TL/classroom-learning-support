"use client";

import { useEffect, useState } from "react";
import { evidenceNames } from "../../lib/evidence";
import { exercisesSchema, levelNames } from "../../lib/exercises";
import type { Exercise } from "../../lib/exercises";
import { manualExercises } from "../../lib/manual-exercises/api";
import type { ManualExerciseRecord } from "../../lib/manual-exercises/api";
import "../presentation/role-panels.css";

function blank(): Exercise[] {
  return (["concept", "explanation", "transfer"] as const).map((level) => ({
    level, question: "", answer: "", explanation: "",
  }));
}
function Editor({ items, onChange }: { items: Exercise[]; onChange: (items: Exercise[]) => void }) {
  const [activeLevel, setActiveLevel] = useState<Exercise["level"]>("concept");
  return <><div className="level-switch" role="group" aria-label="选择人工练习层次">
    {items.map((item) => <button key={item.level} aria-pressed={activeLevel === item.level}
      onClick={() => setActiveLevel(item.level)}>{levelNames[item.level]}</button>)}</div>
    {items.map((item, index) => <fieldset className="exercise-editor" key={item.level}
      hidden={activeLevel !== item.level}>
    <legend>{levelNames[item.level]}</legend>
    {(["question", "answer", "explanation"] as const).map((field) => <label key={field}>
      {{ question: "题干", answer: "答案", explanation: "解释" }[field]}
      <textarea value={item[field]} maxLength={field === "explanation" ? 3000 : 2000}
        onChange={(event) => onChange(items.map((value, position) => position === index
          ? { ...value, [field]: event.target.value } : value))} />
    </label>)}
  </fieldset>)}</>;
}
function ManualReview({ classroomId, record, onSaved }: {
  classroomId: string; record: ManualExerciseRecord; onSaved: (value: ManualExerciseRecord) => void;
}) {
  const [items, setItems] = useState(record.exercises);
  const [revision, setRevision] = useState(record.revision);
  const [checked, setChecked] = useState<Exercise["level"][]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dirty = JSON.stringify(items) !== JSON.stringify(record.exercises);
  async function act(action: "confirmed" | "rejected" | "adopt" | "unadopt") {
    const parsed = exercisesSchema.safeParse(items);
    if (!parsed.success) { setError("三层练习必须分别包含完整题干、答案与解释。"); return; }
    setBusy(true); setError("");
    try {
      const updated = action === "confirmed" || action === "rejected"
        ? await manualExercises.review(classroomId, record.id, revision, action, parsed.data)
        : await manualExercises.adopt(classroomId, record.id, revision, action === "adopt");
      setItems(updated.exercises); setRevision(updated.revision); onSaved(updated);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "人工练习保存失败。"); }
    finally { setBusy(false); }
  }
  return <article className="history-card manual-exercise-review">
    <header className="panel-heading"><h4>人工通用练习</h4><div className="badge-group">
      <span className={`status-badge status-${record.status}`}>{evidenceNames[record.status]}</span>
      <span className="status-badge">{record.adopted ? "已采用" : "未采用"}</span></div></header>
    <details className="audit-details"><summary>查看录入与核验记录</summary>
    <p>版本 {record.revision}，本次编辑依据版本 {revision}；录入人 {record.created_by}；
      核验人 {record.reviewed_by ?? "未核验"}</p></details>
    {error && <p role="alert">{error} 冲突时请刷新后手动载入，不自动覆盖编辑。</p>}
    {record.revision !== revision && <p role="alert">记录已有新版本，当前编辑保留。</p>}
    <details><summary>原始人工初稿（与后续编辑分开保存）</summary>
      {record.initial_exercises.map((item) => <p key={item.level}>
        {levelNames[item.level]}：{item.question}；答案：{item.answer}；解释：{item.explanation}
      </p>)}
    </details>
    <fieldset disabled={busy}>
      <legend>逐题核对与采用</legend>
      <Editor items={items} onChange={(value) => { setItems(value); setChecked([]); }} />
      {items.map((item) => <label key={item.level}>
        <input type="checkbox" checked={checked.includes(item.level)} onChange={(event) => {
          setChecked((previous) => event.target.checked ? [...previous, item.level]
            : previous.filter((level) => level !== item.level));
        }} />我已核对{levelNames[item.level]}题的题干、答案与解释
      </label>)}
      <div className="action-row"><button className="primary-button" disabled={checked.length !== 3}
        onClick={() => void act("confirmed")}>确认人工练习</button>
      <button className="danger-text" onClick={() => void act("rejected")}>驳回人工练习</button></div>
      <div className="adoption-row"><span>课堂使用 · 不作个人报告依据</span>
      <button disabled={record.status !== "confirmed" || record.adopted || dirty || revision !== record.revision}
        onClick={() => void act("adopt")}>采用通用课堂练习</button>
      <button disabled={!record.adopted || dirty || revision !== record.revision}
        onClick={() => void act("unadopt")}>撤销采用</button>
      </div>
      <button onClick={() => {
        setItems(record.exercises); setRevision(record.revision); setChecked([]); setError("");
      }}>载入最新记录并重置编辑</button>
    </fieldset>
  </article>;
}

export function ManualExercises({ classroomId }: { classroomId: string }) {
  const [items, setItems] = useState<Exercise[]>(blank);
  const [requestKey, setRequestKey] = useState<string | null>(null);
  const [records, setRecords] = useState<ManualExerciseRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  function accept(value: ManualExerciseRecord) {
    setRecords((previous) => {
      const old = previous.find((item) => item.id === value.id);
      if (old && old.revision > value.revision) return previous;
      return old ? previous.map((item) => item.id === value.id ? value : item) : [...previous, value];
    });
  }
  useEffect(() => {
    let active = true;
    manualExercises.list(classroomId).then((values) => { if (active) setRecords(values); })
      .catch((failure: unknown) => {
        if (active) setError(failure instanceof Error ? failure.message : "人工练习读取失败。");
      });
    return () => { active = false; };
  }, [classroomId]);
  async function create() {
    const parsed = exercisesSchema.safeParse(items);
    if (!parsed.success) { setError("请完整填写三个层次的题干、答案和解释。"); return; }
    const key = requestKey ?? crypto.randomUUID();
    setRequestKey(key); setBusy(true); setError(""); setNotice("");
    try {
      accept(await manualExercises.create(classroomId, parsed.data, key));
      setNotice("人工初稿已保存，仍需教师核对确认。再次提交同一请求不会新建副本。");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "人工练习保存失败，输入仍保留。"); }
    finally { setBusy(false); }
  }
  async function refresh() {
    setBusy(true); setError("");
    try {
      const values = await manualExercises.list(classroomId);
      setRecords((previous) => values.map((value) => {
        const old = previous.find((item) => item.id === value.id);
        return old && old.revision > value.revision ? old : value;
      }));
    } catch (failure) { setError(failure instanceof Error ? failure.message : "人工练习读取失败。"); }
    finally { setBusy(false); }
  }
  return <section className="support-panel manual-exercises-panel" aria-label="人工通用课堂练习">
    <header className="panel-heading"><div><p className="eyebrow">无需模型 · 教师人工录入</p>
      <h3>通用课堂练习</h3></div><span className="status-badge">通用练习来源</span></header>
    <p className="panel-intro">不依赖个人证据，可用于一般课堂练习；不能直接作为个人报告依据发布。</p>
    {error && <p role="alert">{error}</p>}
    <p role="status">{busy ? "正在保存或读取…" : notice}</p>
    <details><summary>填写一组三层通用练习</summary><fieldset disabled={busy}>
      <legend>人工初稿</legend><Editor items={items} onChange={setItems} />
      <button className="primary-button" onClick={() => void create()}>保存人工初稿（同请求可重试）</button>
      <button onClick={() => { setRequestKey(null); setNotice("下次保存将创建新的人工初稿，当前输入保留。"); }}>
        开始新的人工初稿
      </button>
      <p>已提交请求不能改用不同内容；结果未知时先重试原内容，明确新建时再开始新初稿。</p>
      <button onClick={() => void refresh()}>刷新人工练习</button>
    </fieldset></details>
    {records.map((record) => <ManualReview key={record.id} classroomId={classroomId}
      record={record} onSaved={accept} />)}
  </section>;
}
