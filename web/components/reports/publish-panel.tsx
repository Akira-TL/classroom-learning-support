"use client";

import { useEffect, useRef, useState } from "react";
import type { EvidenceRecord } from "../../lib/evidence";
import { reportsApi, reportStatus } from "../../lib/reports";
import type { ParentReport, ReportPreview } from "../../lib/reports";
import { QuestionQueue } from "./question-queue";
import "../presentation/role-panels.css";

export function PublishPanel({ classroomId, evidence }: { classroomId: string; evidence: EvidenceRecord }) {
  const [summary, setSummary] = useState("");
  const [activity, setActivity] = useState("");
  const [preview, setPreview] = useState<ReportPreview | null>(null);
  const [reports, setReports] = useState<ParentReport[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const publishKey = useRef<string | null>(null);
  const student = evidence.basis.context.student_alias;
  const eligible = evidence.status === "confirmed" && student === "student-01";

  async function refresh() {
    try { setReports(await reportsApi.list(classroomId)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "报告列表读取失败。"); }
  }

  useEffect(() => {
    setPreview(null); publishKey.current = null;
    let active = true;
    reportsApi.list(classroomId).then((items) => { if (active) setReports(items); }).catch((failure: unknown) => {
      if (active) setError(failure instanceof Error ? failure.message : "报告列表读取失败。");
    });
    return () => { active = false; };
  }, [classroomId, evidence.id, evidence.revision, evidence.status]);

  function edit(value: string, field: "summary" | "activity") {
    if (field === "summary") setSummary(value); else setActivity(value);
    setPreview(null); publishKey.current = null; setNotice("");
  }

  async function makePreview() {
    setBusy(true); setError(""); setNotice(""); setPreview(null);
    try {
      setPreview(await reportsApi.preview(classroomId, {
        evidence_id: evidence.id, expected_evidence_revision: evidence.revision, student_id: student,
        summary: summary.trim(), home_activity: activity.trim(),
      }));
      publishKey.current = crypto.randomUUID();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "预览失败。"); }
    finally { setBusy(false); }
  }

  async function publish() {
    if (!preview || !publishKey.current) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const report = await reportsApi.publish(classroomId, preview.content, publishKey.current);
      setNotice(report.status === "published" ? "已发布给绑定家长。" : reportStatus[report.status]);
      await refresh();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "发布未确认成功，可重试同一次请求。"); }
    finally { setBusy(false); }
  }

  async function revoke(report: ParentReport) {
    setBusy(true); setError("");
    try { await reportsApi.revoke(classroomId, report); setNotice("站内旧报告已停止提供。"); await refresh(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "撤回未确认成功，请刷新核对。"); }
    finally { setBusy(false); }
  }

  return <section className="support-panel parent-publish" aria-label="家长摘要发布">
    <p className="eyebrow">发布与接收预览</p><h4>家长学习摘要</h4>
    <p className="panel-intro">教师筛选后的文字与家庭活动，不包含原音频或内部证据说明。</p>
    {evidence.status !== "confirmed" && <div className="empty-state warning-state"><h4>依据已变化 · 等待重核</h4>
      <p>须先确认当前学习证据，才能预览并发布新版。</p></div>}
    {student !== "student-01" && <p>当前演示仅为 student-01 配置家长绑定；该学生尚无可接收家长。</p>}
    {error && <p role="alert">{error}</p>}
    <p role="status">{busy ? "正在核对并提交…" : notice}</p>
    <fieldset disabled={busy || !eligible}>
      <legend>接收学生的绑定家长 · {student} · 依据证据版本 {evidence.revision}</legend>
      <label>家长学习摘要<textarea value={summary} maxLength={4000}
        onChange={(event) => edit(event.target.value, "summary")} /></label>
      <label>家庭活动<textarea value={activity} maxLength={4000}
        onChange={(event) => edit(event.target.value, "activity")} /></label>
      <button disabled={!summary.trim() || !activity.trim()} onClick={() => void makePreview()}>预览接收对象与内容</button>
      {preview && <div className="publish-preview">
        <p className="eyebrow">家长实际接收预览 · 尚未发布</p>
        <p>接收家长：{preview.parent_id} · 绑定学生：{preview.content.student_id}</p>
        <h4>学习摘要</h4><p>{preview.content.summary}</p>
        <h4>家庭活动</h4><p>{preview.content.home_activity}</p><p>{preview.notice}</p>
        <button className="primary-button" onClick={() => void publish()}>确认内容并发布给绑定家长</button>
      </div>}
    </fieldset>
    <button disabled={busy} onClick={() => void refresh()}>刷新发布状态</button>
    {reports.filter((report) => report.evidence_id === evidence.id).map((report) =>
      <article className="history-card" key={report.id}>
      <span className={`status-badge status-${report.status}`}>{reportStatus[report.status]}</span>
      <p className="basis-label">报告版本 {report.revision} · 依据证据版本 {report.evidence_revision}</p>
      {report.status === "stale" && <p>旧报告正文已停止提供，原提问与回复保留。</p>}
      <details className="audit-details"><summary>报告入口与来源记录</summary>
        <p><a href={`/?parent_report=${encodeURIComponent(report.id)}`}>报告入口（需绑定家长登录）</a></p>
        <p>报告编号：{report.id}</p></details>
      {report.status === "published" && <button className="danger-text" disabled={busy}
        onClick={() => void revoke(report)}>撤回此报告</button>}
    </article>)}
    <p className="privacy-note">撤回后站内旧报告及受控入口停止提供；已下载的离线副本不能远程收回。</p>
    <QuestionQueue classroomId={classroomId}
      reportIds={reports.filter((report) => report.evidence_id === evidence.id).map((report) => report.id)} />
  </section>;
}
