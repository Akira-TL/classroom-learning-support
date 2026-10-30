"use client";

import { useCallback, useEffect, useState } from "react";
import { questionStatus, reportsApi } from "../../lib/reports";
import type { ParentQuestion } from "../../lib/reports";

export function QuestionQueue({ classroomId, reportIds }: { classroomId: string; reportIds: string[] }) {
  const [items, setItems] = useState<ParentQuestion[]>([]);
  const [error, setError] = useState("");
  const filterKey = [...reportIds].sort().join(",");
  const load = useCallback(async () => {
    try {
      const incoming = await reportsApi.queue(classroomId);
      setItems((previous) => incoming.filter((item) => reportIds.includes(item.report_id)).map((item) => {
        const old = previous.find((entry) => entry.id === item.id);
        return old && old.revision > item.revision ? old : item;
      }));
      setError("");
    } catch (cause: unknown) { setError(cause instanceof Error ? cause.message : "家长疑问读取失败"); }
  }, [classroomId, filterKey]);
  useEffect(() => {
    let active = true;
    reportsApi.queue(classroomId).then((incoming) => {
      if (active) setItems((previous) => incoming.filter((item) => reportIds.includes(item.report_id)).map((item) => {
        const old = previous.find((entry) => entry.id === item.id);
        return old && old.revision > item.revision ? old : item;
      }));
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "家长疑问读取失败");
    });
    return () => { active = false; };
  }, [classroomId, filterKey]);

  return <section aria-label="教师处理家长疑问">
    <h5>这条学习证据对应的家长疑问</h5>
    <button onClick={() => void load()}>刷新家长疑问</button>
    {error && <p role="alert">{error}</p>}
    {items.length === 0 && <p>对应报告暂无家长疑问。</p>}
    {items.map((item) => <QuestionEditor key={item.id} classroomId={classroomId} item={item}
      onSaved={(incoming) => setItems((previous) => previous.map((entry) => entry.id === incoming.id
        && incoming.revision >= entry.revision ? incoming : entry))} />)}
  </section>;
}

function QuestionEditor({ classroomId, item, onSaved }: {
  classroomId: string; item: ParentQuestion; onSaved: (item: ParentQuestion) => void;
}) {
  const [text, setText] = useState(item.response ?? "");
  const [revision, setRevision] = useState(item.revision);
  const [action, setAction] = useState<"answered" | "dismissed">("answered");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save() {
    setBusy(true); setError("");
    try {
      const result = await reportsApi.resolve(classroomId, item.id, revision, action, text);
      setRevision(result.revision); onSaved(result);
    } catch (cause: unknown) { setError(cause instanceof Error ? cause.message : "回复未保存，填写内容已保留"); }
    finally { setBusy(false); }
  }
  return <article>
    <p>家长：{item.parent_id} · 报告 {item.report_id.slice(0, 8)} · {questionStatus[item.status]}</p>
    <p>{item.text}</p>
    {revision !== item.revision && <div role="status">
      <p>当前版本已变化。服务器回复：{item.response ?? "尚无回复"}。填写内容已保留，请核对。</p>
      <button onClick={() => setRevision(item.revision)}>核对后使用当前版本继续编辑</button>
    </div>}
    <label>处理方式<select value={action} onChange={(event) => {
      setAction(event.target.value === "dismissed" ? "dismissed" : "answered");
    }}><option value="answered">回复家长</option><option value="dismissed">说明不采纳原因</option></select></label>
    <label>教师回复<textarea maxLength={3000} value={text} onChange={(event) => setText(event.target.value)} /></label>
    <button disabled={busy || !text.trim() || revision !== item.revision} onClick={() => void save()}>保存处理结果</button>
    {error && <p role="alert">{error}</p>}
  </article>;
}
