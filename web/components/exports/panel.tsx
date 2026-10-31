"use client";

import { useEffect, useRef, useState } from "react";
import type { PlanRecord } from "../../lib/plans";
import { downloadUrl, exportsApi, exportStatus, previewHtml, statusUrl } from "../../lib/exports/api";
import type { CreateExport, ExportMetadata } from "../../lib/exports/api";
import { ExportRequests, mergeExportList, preferExport } from "../../lib/exports/coordination";
import type { RequestToken } from "../../lib/exports/coordination";
import { reportsApi } from "../../lib/reports";
import type { ParentReport } from "../../lib/reports";
import "../presentation/role-panels.css";

export function ExportPanel({ classroomId, plan }: { classroomId: string; plan: PlanRecord }) {
  const [reports, setReports] = useState<ParentReport[]>([]);
  const [exports, setExports] = useState<ExportMetadata[]>([]);
  const [parentId, setParentId] = useState("");
  const [attempt, setAttempt] = useState<{ classroomId: string; body: CreateExport } | null>(null);
  const [pending, setPending] = useState(0);
  const [verified, setVerified] = useState<RequestToken | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const requests = useRef(new ExportRequests());
  const context = JSON.stringify([classroomId, plan.id, plan.revision, plan.status]);
  const latestContext = useRef(context);
  latestContext.current = context;
  const trusted = verified !== null && requests.current.current(verified, context);
  const busy = pending > 0;
  const candidates = reports.filter((report) => report.status === "published"
    && report.student_id === plan.content.target_student);
  const selectedAvailable = !parentId || candidates.some((item) => item.id === parentId);

  function begin() {
    const token = requests.current.begin(context);
    setPending(requests.current.count()); setVerified(null); setError(""); setNotice("");
    return token;
  }
  function current(token: RequestToken) { return requests.current.current(token, latestContext.current); }
  function finish(token: RequestToken) {
    requests.current.finish(token); setPending(requests.current.count());
  }
  function fail(token: RequestToken, cause: unknown) {
    if (current(token)) { setVerified(null); setError(cause instanceof Error ? cause.message : "报告状态未核实"); }
  }
  async function read(token: RequestToken) {
    const [parentReports, metadata] = await Promise.all([reportsApi.list(classroomId), exportsApi.list(classroomId)]);
    if (!current(token)) return;
    setReports(parentReports);
    setExports((previous) => mergeExportList(previous, metadata)); setVerified(token);
  }
  async function load() {
    const token = begin();
    try { await read(token); } catch (cause: unknown) { fail(token, cause); } finally { finish(token); }
  }
  useEffect(() => {
    void load();
    return () => { requests.current.cancel(); };
  }, [context]);

  async function create() {
    if (!trusted || busy || attempt && attempt.classroomId !== classroomId) return;
    const parent = candidates.find((report) => report.id === parentId);
    if (!attempt && parentId && !parent) { setError("所选家长报告已不可用，请核对后重新选择。"); return; }
    const snapshot = attempt ?? { classroomId, body: {
      plan_id: plan.id, expected_plan_revision: plan.revision,
      parent_report_id: parent?.id ?? null, expected_parent_revision: parent?.revision ?? null,
      idempotency_key: crypto.randomUUID(),
    } };
    setAttempt(snapshot);
    const token = begin();
    try {
      const result = await exportsApi.create(snapshot.classroomId, snapshot.body);
      if (!current(token)) return;
      setExports((previous) => [...previous.filter((item) => item.id !== result.id),
        preferExport(previous.find((item) => item.id === result.id), result)]);
      setNotice(`已收到报告创建返回，版本 ${result.revision}；有效状态以重新核实后的列表为准。`);
      await read(token);
    } catch (cause: unknown) { fail(token, cause); } finally { finish(token); }
  }
  async function revoke(metadata: ExportMetadata) {
    if (!trusted || busy) return;
    const token = begin();
    try {
      const result = await exportsApi.revoke(classroomId, metadata);
      if (!current(token)) return;
      setExports((previous) => previous.map((item) => item.id === result.id ? preferExport(item, result) : item));
      setNotice("受控报告入口已撤回。"); await read(token);
    } catch (cause: unknown) { fail(token, cause); } finally { finish(token); }
  }
  async function preview(metadata: ExportMetadata) {
    if (!trusted || busy) return;
    const token = begin();
    let url: string | null = null;
    try {
      url = await previewHtml(metadata.id);
      if (!current(token)) { URL.revokeObjectURL(url); return; }
      window.open(url, "_blank", "noopener,noreferrer");
      const opened = url; window.setTimeout(() => URL.revokeObjectURL(opened), 60_000);
      setNotice("已请求新窗口预览；拦截时可使用受控下载链接。"); await read(token);
    } catch (cause: unknown) { if (url) URL.revokeObjectURL(url); fail(token, cause); }
    finally { finish(token); }
  }

  return <section className="support-panel export-panel" aria-label="教师报告导出">
    <p className="eyebrow">教学资料归档</p><h4>教师教学支持报告</h4>
    <p className="panel-intro">根据已确认教学安排创建 HTML 报告，来源变化后须重新核实。</p>
    {!trusted && <p role="status">当前来源或报告状态待核实，暂不提供有效报告操作。</p>}
    {plan.status !== "confirmed" && <p>当前教学安排尚未确认或已过期，不能创建正式报告。</p>}
    {error && <p role="alert">{error} 原选择和创建请求已保留，请刷新核对后重试。</p>}
    <p role="status">{busy ? "正在核对或处理报告请求…" : notice}</p>
    <label>可选附加同学生的家长报告<select value={parentId} disabled={busy || !trusted}
      onChange={(event) => { setParentId(event.target.value); setNotice(""); }}>
      <option value="">不附加家长报告</option>
      {!selectedAvailable && <option value={parentId}>原选择待核实或已失效</option>}
      {candidates.map((report) => <option key={report.id} value={report.id}>
        {report.student_id} · {new Date(report.published_at).toLocaleString("zh-CN")} · 版本 {report.revision}</option>)}
    </select></label>
    {attempt && <details className="audit-details"><summary>原创建请求已保留 · 采用原参数重试</summary>
      <p>课堂 {attempt.classroomId} · 计划 {attempt.body.plan_id} · 版本 {attempt.body.expected_plan_revision}。</p>
      <p>重试使用原参数；使用新选择请明确准备新请求。</p></details>}
    <button className="primary-button" type="button" disabled={busy || !trusted || plan.status !== "confirmed"
      || Boolean(attempt && attempt.classroomId !== classroomId)} onClick={() => void create()}>
      {attempt ? "重试同一次报告创建请求" : "创建教师报告"}</button>
    {attempt && <button type="button" disabled={busy} onClick={() => {
      setAttempt(null); setNotice("已准备新请求，下次点击创建才会使用当前选择。");
    }}>准备创建另一份报告</button>}
    <button type="button" disabled={busy} onClick={() => void load()}>刷新报告与有效状态</button>
    {trusted && exports.length === 0 && <p>本课堂尚无教师导出报告。</p>}
    {exports.map((metadata) => <article className="history-card" key={metadata.id}>
      <header className="panel-heading"><strong>教师教学支持报告</strong>
        <span className={`status-badge status-${trusted ? metadata.status : "pending"}`}>
          {trusted ? exportStatus[metadata.status] : "状态待重新核实"}</span></header>
      <p className="basis-label">版本 {metadata.revision} · {new Date(metadata.created_at).toLocaleString("zh-CN")}</p>
      {trusted && metadata.status === "stale" && <p>来源已变化，旧报告下载入口已关闭。请重核后创建新版。</p>}
      {trusted && !busy && metadata.status === "active" && <>
        <button type="button" onClick={() => void preview(metadata)}>预览静态报告</button>
        <a className="download-link" href={downloadUrl(metadata.id)}>下载 HTML 报告</a>
        <button className="danger-text" type="button" onClick={() => void revoke(metadata)}>撤回此报告</button>
      </>}
      <details className="audit-details"><summary>报告编号与受控状态入口</summary><p>报告编号：{metadata.id}</p>
        <a href={statusUrl(metadata.id)} target="_blank" rel="noopener noreferrer">查询状态（仅元数据）</a></details>
    </article>)}
    <p className="privacy-note">受控入口会检查当前权限与依据；已下载的离线副本不能远程收回，请核对状态。</p>
  </section>;
}
