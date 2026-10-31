"use client";

import { useCallback, useEffect, useState } from "react";
import { studentsApi } from "../../lib/students/api";
import { feedbackNames } from "../../lib/students/types";
import type { FeedbackSource, StudentFeedback } from "../../lib/students/types";
import "../presentation/role-panels.css";

export function StudentFeedbackQueue({ classroomId }: { classroomId: string }) {
  const [items, setItems] = useState<StudentFeedback[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try { setItems(await studentsApi.queue(classroomId)); setError(""); }
    catch (cause: unknown) { setError(cause instanceof Error ? cause.message : "反馈队列加载失败"); }
  }, [classroomId]);
  useEffect(() => { void load(); }, [load]);
  return <section className="support-panel student-feedback-queue"><p className="eyebrow">学生反馈</p>
    <h3>反馈与核对申请</h3>
    <p className="panel-intro">受理后请定位原发言，通过独立的课堂纠错操作修改事实并重新核验。</p>
    <button onClick={() => void load()}>刷新队列</button>
    {error && <p role="alert">{error}</p>}
    {items.length === 0 && <p>暂无学生反馈。</p>}
    {items.map((item) => <FeedbackItem key={item.id} classroomId={classroomId} item={item}
      onSaved={(incoming) => setItems((previous) => previous.map(
        (entry) => entry.id === incoming.id ? incoming : entry,
      ))} />)}
  </section>;
}

function FeedbackItem({ classroomId, item, onSaved }: {
  classroomId: string; item: StudentFeedback; onSaved: (item: StudentFeedback) => void;
}) {
  const [response, setResponse] = useState(item.response ?? "");
  const [editingRevision, setEditingRevision] = useState(item.revision);
  const [source, setSource] = useState<FeedbackSource | null>(null);
  const [action, setAction] = useState<"accepted" | "rejected" | "answered">("accepted");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function locate() {
    setError("");
    try { setSource(await studentsApi.source(classroomId, item.id)); }
    catch (cause: unknown) { setError(cause instanceof Error ? cause.message : "来源读取失败"); }
  }
  async function save() {
    setBusy(true); setError("");
    try {
      const result = await studentsApi.handle(classroomId, item.id, editingRevision, action, response);
      setEditingRevision(result.revision); onSaved(result);
    }
    catch (cause: unknown) { setError(cause instanceof Error ? cause.message : "处理失败，填写内容已保留"); }
    finally { setBusy(false); }
  }
  return <article className="history-card student-feedback-item">
    <header className="panel-heading"><strong>{item.student_id} ·
      {item.kind === "correction" ? "核对申请" : "练习反馈"}</strong>
      <span className={`status-badge status-${item.status}`}>{feedbackNames[item.status]}</span></header>
    <p>{item.text}</p><p>原报告版本 {item.report_revision} · 反馈版本 {item.revision}</p>
    {editingRevision !== item.revision && <div role="status">
      <p>服务器反馈版本已变化，当前填写内容已保留。服务器回复：{item.response ?? "尚无回复"}</p>
      <button onClick={() => setEditingRevision(item.revision)}>核对后采用当前反馈版本继续编辑</button>
    </div>}
    <button disabled={busy} onClick={() => void locate()}>查看原发言位置</button>
    {source && <div className="source-location"><p>原报告学生：{source.original_student_id} ·
      当前归属：{source.current_student_alias ?? "待确认"} · 发言版本 {source.current_utterance_version}</p>
      <a href={`#${encodeURIComponent(`utterance-${source.session_id}-${source.segment_id}`)}`}>返回原发言核验</a>
      <details className="audit-details"><summary>来源位置记录</summary>
        <p>会话：{source.session_id} · 片段：{source.segment_id}</p></details></div>}
    <label>处理方式<select value={action} onChange={(event) => {
      const value = event.target.value;
      setAction(value === "rejected" || value === "answered" ? value : "accepted");
    }}><option value="accepted">受理并继续核对</option><option value="rejected">驳回并说明</option>
      <option value="answered">回复</option></select></label>
    <label>给学生的处理说明<textarea value={response} maxLength={4000}
      onChange={(event) => setResponse(event.target.value)} /></label>
    <button className="primary-button" disabled={busy || !response.trim() || editingRevision !== item.revision}
      onClick={() => void save()}>保存处理结果</button>
    {error && <p role="alert">{error}</p>}
  </article>;
}
