"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ExerciseRecord } from "../../lib/exercises";
import { studentsApi } from "../../lib/students/api";
import { publishSchema, reportNames } from "../../lib/students/types";
import type { ReportSummary, StudentPreview } from "../../lib/students/types";
import "../presentation/role-panels.css";

function newer(previous: ReportSummary | undefined, incoming: ReportSummary): ReportSummary {
  if (!previous) return incoming;
  return previous.revision > incoming.revision || previous.revision === incoming.revision
    && previous.status !== "published" && incoming.status === "published" ? previous : incoming;
}

export function StudentPublishPanel({ classroomId, exercise }: { classroomId: string; exercise: ExerciseRecord }) {
  const [feedback, setFeedback] = useState("");
  const [preview, setPreview] = useState<StudentPreview | null>(null);
  const [previewSignature, setPreviewSignature] = useState("");
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [listState, setListState] = useState<"loading" | "ready" | "unknown">("loading");
  const [listSource, setListSource] = useState("");
  const [editorOpen, setEditorOpen] = useState<boolean | null>(null);
  const pending = useRef({ signature: "", key: "" });
  const listRequest = useRef(0);
  const operationCounter = useRef(0);
  const activeOperation = useRef<number | null>(null);
  const source = JSON.stringify([classroomId, exercise.id, exercise.revision, exercise.status]);
  const currentSource = useRef(source);
  currentSource.current = source;
  const student = exercise.original.evidence.draft.context.student_alias;
  const body = {
    exercise_set_id: exercise.id, expected_exercise_revision: exercise.revision, student_id: student, feedback,
  };
  const signature = JSON.stringify([source, body]);
  const allowed = exercise.status === "confirmed" && Boolean(feedback.trim());
  const listReady = listSource === source && listState === "ready";
  const visibleReports = reports.filter((item) => item.classroom_id === classroomId && item.student_id === student);
  const showEditor = editorOpen ?? visibleReports.length === 0;

  const refreshReports = useCallback(async () => {
    const version = ++listRequest.current;
    setListState("loading"); setPreview(null); setPreviewSignature("");
    try {
      const incoming = await studentsApi.classReports(classroomId);
      if (version !== listRequest.current || currentSource.current !== source) return;
      setReports((previous) => incoming.map((item) => newer(previous.find((old) => old.id === item.id), item)));
      setListSource(source); setListState("ready");
    } catch (cause: unknown) {
      if (version !== listRequest.current || currentSource.current !== source) return;
      setListState("unknown");
      setError(cause instanceof Error ? cause.message : "发布状态读取失败，不能把旧记录视为仍然有效。");
    }
  }, [classroomId, source]);

  useEffect(() => {
    setPreview(null); setPreviewSignature(""); setMessage("");
    activeOperation.current = null; setBusy(false);
    void refreshReports();
    return () => { listRequest.current++; activeOperation.current = null; };
  }, [refreshReports]);

  function begin(): number | null {
    if (activeOperation.current !== null) return null;
    const operation = ++operationCounter.current;
    activeOperation.current = operation; setBusy(true); setError(""); setMessage("");
    return operation;
  }
  function isCurrent(operation: number): boolean {
    return activeOperation.current === operation && currentSource.current === source;
  }
  function finish(operation: number) {
    if (isCurrent(operation)) { activeOperation.current = null; setBusy(false); }
  }
  function saveReport(incoming: ReportSummary) {
    setReports((items) => {
      const old = items.find((item) => item.id === incoming.id);
      const value = newer(old, incoming);
      return old ? items.map((item) => item.id === incoming.id ? value : item) : [value, ...items];
    });
  }

  async function showPreview() {
    if (!allowed) return;
    const operation = begin();
    if (operation === null) return;
    try {
      const parsed = publishSchema.parse(body);
      const result = await studentsApi.preview(classroomId, parsed);
      if (isCurrent(operation)) { setPreview(result); setPreviewSignature(signature); }
    } catch (cause: unknown) {
      if (isCurrent(operation)) setError(cause instanceof Error ? cause.message : "预览失败");
    } finally { finish(operation); }
  }

  async function publish() {
    if (!allowed || !preview || previewSignature !== signature) return;
    const operation = begin();
    if (operation === null) return;
    listRequest.current++; setListState("unknown");
    if (pending.current.signature !== signature) pending.current = { signature, key: crypto.randomUUID() };
    try {
      const result = await studentsApi.publish(classroomId, publishSchema.parse(body), pending.current.key);
      if (!isCurrent(operation)) return;
      saveReport(result); setPreview(null);
      setMessage(`报告发布请求已完成，返回版本 ${result.revision}；当前有效状态以下方刷新结果为准。`);
      await refreshReports();
    } catch (cause: unknown) {
      if (isCurrent(operation)) setError(cause instanceof Error ? cause.message : "发布失败，原反馈已保留");
    } finally { finish(operation); }
  }

  async function revoke(report: ReportSummary) {
    if (!listReady || report.status !== "published") return;
    const operation = begin();
    if (operation === null) return;
    listRequest.current++; setListState("unknown");
    try {
      const result = await studentsApi.revoke(classroomId, report.id, report.revision);
      if (!isCurrent(operation)) return;
      saveReport(result);
      setMessage("报告已撤回，学生站内旧地址不再提供正文。");
      await refreshReports();
    } catch (cause: unknown) {
      if (isCurrent(operation)) setError(cause instanceof Error ? cause.message : "撤回未确认，请刷新状态后再操作。");
    } finally { finish(operation); }
  }

  return <section className="support-panel student-publish" aria-label="向学生发布反馈">
    <header className="panel-heading"><h4>学生反馈与练习</h4>
      <span className={`status-badge status-${exercise.status}`}>
        {exercise.status === "confirmed" ? "练习已确认" : "练习待重核"}</span></header>
    <p className="basis-label">接收学生：{student} · 练习版本 {exercise.revision}</p>
    {exercise.status !== "confirmed" && <p className="completion-note">
      练习尚未确认或依据已失效，不能预览或发布新版。请返回教学支持重核，反馈草稿保留。</p>}
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    <button disabled={busy || listState === "loading"} onClick={() => {
      setError(""); void refreshReports();
    }}>刷新发布状态</button>
    {!listReady && <p role="status">发布状态{listState === "loading" ? "正在重新核对" : "尚未确认"}；
      旧记录不作为有效发布证明，教师反馈草稿仍保留。</p>}
    {visibleReports.map((item) => <article className="history-card" key={item.id}>
      <span className={`status-badge status-${listReady ? item.status : "pending"}`}>
        {listReady ? reportNames[item.status] : "状态待刷新"}</span><span className="basis-label">报告版本 {item.revision}</span>
      {listReady && item.status !== "published" && <div className="empty-state warning-state">
        <h4>旧报告正文已停止提供</h4><p>{item.status === "stale"
          ? "依据已变化，请重新核验后发布新版。" : "教师已撤回此报告，站内不再提供旧正文。"}</p></div>}
      <details className="audit-details"><summary>报告编号与接收对象</summary>
        <p>报告：{item.id}</p><p>接收学生：{item.student_id} · 课堂：{item.classroom_id}</p></details>
      {listReady && item.status === "published"
        && <button className="danger-text" disabled={busy} onClick={() => void revoke(item)}>撤回此报告</button>}
    </article>)}
    <details open={showEditor}><summary onClick={(event) => {
      event.preventDefault(); setEditorOpen(!showEditor);
    }}>编写新版反馈与练习发布</summary>
      <p className="panel-intro">仅发送教师核验后的反馈与练习，预览后仍需明确确认发布。</p>
      <label>教师给学生的反馈<textarea maxLength={6000} value={feedback} onChange={(event) => {
        setFeedback(event.target.value); setPreview(null);
      }} /></label>
      <button disabled={busy || !allowed} onClick={() => void showPreview()}>预览接收内容</button>
      {preview && previewSignature === signature && <section className="publish-preview" aria-label="学生报告预览">
        <p className="eyebrow">学生实际接收预览 · 尚未发布</p><h4>教师反馈</h4><p>{preview.feedback}</p>
        {preview.exercises.map((item, index) => <div className="preview-exercise" key={item.level}>
          <h5>练习 {index + 1}</h5><p>{item.question}</p>
          <details><summary>答案与解释</summary><p>{item.answer}</p><p>{item.explanation}</p></details></div>)}
        <button className="primary-button" disabled={busy || !allowed}
          onClick={() => void publish()}>确认向该学生发布</button>
      </section>}
    </details>
    <p className="privacy-note">学生端不显示原音频或教师内部证据备注；已下载的离线副本不能远程收回。</p>
  </section>;
}
