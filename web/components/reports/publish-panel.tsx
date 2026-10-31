"use client";

import { useEffect, useRef, useState } from "react";
import type { EvidenceRecord } from "../../lib/evidence";
import { reportsApi, reportStatus } from "../../lib/reports";
import type { ParentReport, ReportPreview } from "../../lib/reports";
import { QuestionQueue } from "./question-queue";
import { mergeParentReports, ParentReportRequests, preferParentReport } from "./coordination";
import type { ReportToken } from "./coordination";
import "../presentation/role-panels.css";

export function PublishPanel({ classroomId, evidence }: { classroomId: string; evidence: EvidenceRecord }) {
  const [summary, setSummary] = useState("");
  const [activity, setActivity] = useState("");
  const [preview, setPreview] = useState<ReportPreview | null>(null);
  const [previewSource, setPreviewSource] = useState("");
  const [reports, setReports] = useState<ParentReport[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [listState, setListState] = useState<"loading" | "ready" | "unknown">("loading");
  const [listSource, setListSource] = useState("");
  const source = JSON.stringify([classroomId, evidence.id, evidence.revision, evidence.status]);
  const requests = useRef(new ParentReportRequests());
  requests.current.setSource(source);
  const publishKey = useRef<string | null>(null);
  const student = evidence.basis.context.student_alias;
  const listReady = listSource === source && listState === "ready";
  const eligible = evidence.status === "confirmed" && student === "student-01" && listReady;

  async function refresh() {
    const token = requests.current.beginList(source);
    if (!token) return;
    setListState("loading");
    try {
      const incoming = await reportsApi.list(classroomId);
      if (!requests.current.current(token)) return;
      setReports((previous) => mergeParentReports(previous, incoming));
      setListSource(source); setListState("ready");
    } catch (failure) {
      if (!requests.current.current(token)) return;
      setListState("unknown"); setError(failure instanceof Error ? failure.message : "报告列表读取失败。");
    }
  }

  useEffect(() => {
    setPreview(null); setPreviewSource(""); publishKey.current = null; setBusy(false); setNotice("");
    void refresh();
    return () => { requests.current.cancel(); };
  }, [source]);

  function edit(value: string, field: "summary" | "activity") {
    if (field === "summary") setSummary(value); else setActivity(value);
    setPreview(null); publishKey.current = null; setNotice("");
  }

  function begin(mutation: boolean): ReportToken | null {
    const token = requests.current.beginOperation(source, mutation);
    if (!token) return null;
    setBusy(true); setError(""); setNotice("");
    if (mutation) setListState("unknown");
    return token;
  }
  function finish(token: ReportToken) {
    if (requests.current.finish(token)) setBusy(false);
  }
  function saveReport(incoming: ParentReport) {
    setReports((previous) => {
      const old = previous.find((item) => item.id === incoming.id);
      const preferred = preferParentReport(old, incoming);
      return old ? previous.map((item) => item.id === incoming.id ? preferred : item) : [preferred, ...previous];
    });
  }

  async function makePreview() {
    if (!eligible) return;
    const token = begin(false);
    if (!token) return;
    setPreview(null); setPreviewSource("");
    try {
      const incoming = await reportsApi.preview(classroomId, {
        evidence_id: evidence.id, expected_evidence_revision: evidence.revision, student_id: student,
        summary: summary.trim(), home_activity: activity.trim(),
      });
      if (!requests.current.current(token)) return;
      setPreview(incoming); setPreviewSource(source);
      publishKey.current = crypto.randomUUID();
    } catch (failure) {
      if (requests.current.current(token)) setError(failure instanceof Error ? failure.message : "预览失败。");
    } finally { finish(token); }
  }

  async function publish() {
    if (!preview || !publishKey.current || !eligible || previewSource !== source) return;
    const token = begin(true);
    if (!token) return;
    try {
      const report = await reportsApi.publish(classroomId, preview.content, publishKey.current);
      if (!requests.current.current(token)) return;
      saveReport(report);
      setNotice(report.status === "published" ? "已发布给绑定家长。" : reportStatus[report.status]);
      await refresh();
    } catch (failure) {
      if (requests.current.current(token)) {
        setError(failure instanceof Error ? failure.message : "发布未确认成功，可重试同一次请求。");
      }
    } finally { finish(token); }
  }

  async function revoke(report: ParentReport) {
    if (!listReady || report.status !== "published") return;
    const token = begin(true);
    if (!token) return;
    try {
      const incoming = await reportsApi.revoke(classroomId, report);
      if (!requests.current.current(token)) return;
      saveReport(incoming); setNotice("站内旧报告已停止提供。"); await refresh();
    } catch (failure) {
      if (requests.current.current(token)) {
        setError(failure instanceof Error ? failure.message : "撤回未确认成功，请刷新核对。");
      }
    } finally { finish(token); }
  }

  return <section className="support-panel parent-publish" aria-label="家长摘要发布">
    <p className="eyebrow">发布与接收预览</p><h4>家长学习摘要</h4>
    <p className="panel-intro">教师筛选后的文字与家庭活动，不包含原音频或内部证据说明。</p>
    {evidence.status !== "confirmed" && <div className="empty-state warning-state"><h4>依据已变化 · 等待重核</h4>
      <p>须先确认当前学习证据，才能预览并发布新版。</p></div>}
    {student !== "student-01" && <p>当前演示仅为 student-01 配置家长绑定；该学生尚无可接收家长。</p>}
    {error && <p role="alert">{error}</p>}
    <p role="status">{busy ? "正在核对并提交…" : notice}</p>
    {!listReady && <p role="status">发布状态{listState === "loading" ? "正在重新核对" : "尚未确认"}；
      旧记录不作为有效发布证明，暂不能预览或发布新版。</p>}
    <fieldset disabled={busy || !eligible}>
      <legend>接收学生的绑定家长 · {student} · 依据证据版本 {evidence.revision}</legend>
      <label>家长学习摘要<textarea value={summary} maxLength={4000}
        onChange={(event) => edit(event.target.value, "summary")} /></label>
      <label>家庭活动<textarea value={activity} maxLength={4000}
        onChange={(event) => edit(event.target.value, "activity")} /></label>
      <button disabled={!summary.trim() || !activity.trim()} onClick={() => void makePreview()}>预览接收对象与内容</button>
      {preview && previewSource === source && eligible && <div className="publish-preview">
        <p className="eyebrow">家长实际接收预览 · 尚未发布</p>
        <p>接收家长：{preview.parent_id} · 绑定学生：{preview.content.student_id}</p>
        <h4>学习摘要</h4><p>{preview.content.summary}</p>
        <h4>家庭活动</h4><p>{preview.content.home_activity}</p><p>{preview.notice}</p>
        <button className="primary-button" onClick={() => void publish()}>确认内容并发布给绑定家长</button>
      </div>}
    </fieldset>
    <button disabled={busy || listState === "loading"} onClick={() => {
      setError(""); void refresh();
    }}>刷新发布状态</button>
    {reports.filter((report) => report.evidence_id === evidence.id).map((report) =>
      <article className="history-card" key={report.id}>
      <span className={`status-badge status-${listReady ? report.status : "pending"}`}>
        {listReady ? reportStatus[report.status] : "状态待刷新"}</span>
      <p className="basis-label">报告版本 {report.revision} · 依据证据版本 {report.evidence_revision}</p>
      {listReady && report.status === "stale" && <p>旧报告正文已停止提供，原提问与回复保留。</p>}
      <details className="audit-details"><summary>报告入口与来源记录</summary>
        <p><a href={`/?parent_report=${encodeURIComponent(report.id)}`}>报告入口（需绑定家长登录）</a></p>
        <p>报告编号：{report.id}</p></details>
      {listReady && report.status === "published" && <button className="danger-text" disabled={busy}
        onClick={() => void revoke(report)}>撤回此报告</button>}
    </article>)}
    <p className="privacy-note">撤回后站内旧报告及受控入口停止提供；已下载的离线副本不能远程收回。</p>
    <QuestionQueue classroomId={classroomId}
      reportIds={reports.filter((report) => report.evidence_id === evidence.id).map((report) => report.id)} />
  </section>;
}
