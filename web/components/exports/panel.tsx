"use client";

import { useEffect, useState } from "react";
import type { PlanRecord } from "../../lib/plans";
import { downloadUrl, exportsApi, exportStatus, previewHtml, statusUrl } from "../../lib/exports/api";
import type { CreateExport, ExportMetadata } from "../../lib/exports/api";
import { reportsApi } from "../../lib/reports";
import type { ParentReport } from "../../lib/reports";

export function ExportPanel({ classroomId, plan }: { classroomId: string; plan: PlanRecord }) {
  const [reports, setReports] = useState<ParentReport[]>([]);
  const [exports, setExports] = useState<ExportMetadata[]>([]);
  const [parentId, setParentId] = useState("");
  const [attempt, setAttempt] = useState<CreateExport | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const candidates = reports.filter((report) => report.status === "published"
    && report.student_id === plan.content.target_student);

  async function load() {
    setLoading(true);
    try {
      const [parentReports, metadata] = await Promise.all([reportsApi.list(classroomId), exportsApi.list(classroomId)]);
      setReports(parentReports); setExports(metadata);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "报告状态读取失败。");
    } finally { setLoading(false); }
  }

  useEffect(() => {
    setAttempt(null); setParentId(""); setReports([]); setExports([]);
    let active = true;
    setLoading(true);
    Promise.all([reportsApi.list(classroomId), exportsApi.list(classroomId)]).then(([parentReports, metadata]) => {
      if (active) { setReports(parentReports); setExports(metadata); }
    }).catch((failure: unknown) => {
      if (active) setError(failure instanceof Error ? failure.message : "报告读取失败。");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [classroomId, plan.id, plan.revision, plan.status]);

  async function create() {
    const parent = candidates.find((report) => report.id === parentId);
    if (parentId && !parent) { setError("所选家长报告已不可用，请刷新后重新选择。"); return; }
    const body = attempt ?? {
      plan_id: plan.id, expected_plan_revision: plan.revision,
      parent_report_id: parent?.id ?? null, expected_parent_revision: parent?.revision ?? null,
      idempotency_key: crypto.randomUUID(),
    };
    setAttempt(body); setBusy(true); setError(""); setNotice("");
    try {
      const metadata = await exportsApi.create(classroomId, body);
      setNotice(`报告创建请求已确认：${exportStatus[metadata.status]}，版本 ${metadata.revision}。`);
      await load();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "未确认创建成功，可重试同一次请求。"); }
    finally { setBusy(false); }
  }

  async function revoke(metadata: ExportMetadata) {
    setBusy(true); setError("");
    try { await exportsApi.revoke(classroomId, metadata); setNotice("受控报告入口已撤回。"); await load(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "撤回未确认成功，请刷新核对。"); }
    finally { setBusy(false); }
  }

  async function preview(metadata: ExportMetadata) {
    setBusy(true); setError("");
    try {
      const url = await previewHtml(metadata.id);
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      setNotice("已请求在新窗口预览；若浏览器拦截了弹窗，可使用受控下载链接。");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "预览失败。"); }
    finally { setBusy(false); }
  }

  return <section aria-label="教师报告导出">
    <h4>导出教师教学支持报告</h4>
    <p>仅根据当前已确认教学安排创建静态 HTML 报告，不调用模型。点击创建前请核对证据和题目。</p>
    {plan.status !== "confirmed" && <p>当前教学安排尚未确认或已过期，不能创建正式报告。</p>}
    {error && <p role="alert">{error}</p>}
    <p role="status">{loading ? "正在读取报告状态…" : notice}</p>
    <label>可选附加同学生的家长报告<select value={parentId} disabled={busy || loading}
      onChange={(event) => { setParentId(event.target.value); setAttempt(null); setNotice(""); }}>
      <option value="">不附加家长报告</option>
      {candidates.map((report) => <option key={report.id} value={report.id}>
        {report.student_id} · 家长报告 {report.id} · 版本 {report.revision}
      </option>)}
    </select></label>
    <button type="button" disabled={busy || loading || plan.status !== "confirmed"} onClick={() => void create()}>
      {attempt ? "重试同一次报告创建请求" : "创建教师报告"}
    </button>
    {attempt && <button type="button" disabled={busy} onClick={() => {
      setAttempt(null); setNotice("已准备新请求，下次点击创建才会生成新报告。");
    }}>准备创建另一份报告</button>}
    <button type="button" disabled={busy || loading} onClick={() => void load()}>刷新报告与有效状态</button>
    {!loading && exports.length === 0 && <p>本课堂尚无教师导出报告。</p>}
    {exports.map((metadata) => <article key={metadata.id}>
      <p>报告 {metadata.id}：{exportStatus[metadata.status]} · 版本 {metadata.revision}
        · {new Date(metadata.created_at).toLocaleString("zh-CN")}</p>
      <a href={statusUrl(metadata.id)} target="_blank" rel="noopener noreferrer">查询状态（仅元数据）</a>
      {metadata.status === "active" && <>
        <button type="button" disabled={busy} onClick={() => void preview(metadata)}>预览静态报告</button>
        <a href={downloadUrl(metadata.id)}>下载教师 HTML 报告</a>
        <button type="button" disabled={busy} onClick={() => void revoke(metadata)}>撤回此报告</button>
      </>}
    </article>)}
    <p>站内受控入口会检查当前权限与依据；已下载的离线副本不能远程收回，使用前需核对状态。</p>
  </section>;
}
