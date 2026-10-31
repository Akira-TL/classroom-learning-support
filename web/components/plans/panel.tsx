"use client";

import { useEffect, useRef, useState } from "react";
import { taskNames } from "../../lib/evidence";
import type { EvidenceRecord } from "../../lib/evidence";
import { mergePlans, plansApi } from "../../lib/plans";
import type { GeneratePlan, PlanRecord, PlanResult } from "../../lib/plans";
import { PlanReview } from "./review";
import { ExportPanel } from "../exports/panel";
import { choosePublicationTask, publicationContext, publicationRecord } from "../presentation/publication-source";
import type { PublicationRead } from "../presentation/publication-source";
import "../presentation/role-panels.css";

export function PlanPanel({ classroomId, evidence, view = "teaching" }: {
  classroomId: string; evidence: EvidenceRecord; view?: "teaching" | "publishing";
}) {
  const [results, setResults] = useState<PlanResult[]>([]);
  const [attempt, setAttempt] = useState<GeneratePlan | null>(null);
  const [busy, setBusy] = useState(false);
  const context = publicationContext(classroomId, evidence);
  const [read, setRead] = useState<PublicationRead>({ context, status: "loading" });
  const [selectedTask, setSelectedTask] = useState("");
  const currentContext = useRef(context);
  currentContext.current = context;
  const listRequest = useRef(0);
  const loading = read.context !== context || read.status === "loading";
  const loaded = read.context === context && read.status === "ready";
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function accept(incoming: PlanResult[]) {
    const matched = incoming.filter((item) => item.task.request.evidence_id === evidence.id);
    setResults((previous) => matched.map((item) => mergePlans(
      previous.find((result) => result.task.id === item.task.id), item,
    )));
    setAttempt((previous) => previous ?? matched.at(-1)?.task.request ?? null);
    setSelectedTask((previous) => choosePublicationTask(previous, matched.map((item) => ({
      id: item.task.id, valid: item.task.status === "succeeded" && item.plan?.status === "confirmed"
        && item.plan.evidence_revision === evidence.revision && evidence.status === "confirmed",
    }))));
  }
  useEffect(() => {
    void refresh();
    return () => { listRequest.current++; };
  }, [context]);

  async function refresh() {
    const generation = ++listRequest.current;
    setRead({ context, status: "loading" }); setError("");
    try {
      const incoming = await plansApi.list(classroomId);
      if (generation !== listRequest.current || context !== currentContext.current) return;
      accept(incoming); setRead({ context, status: "ready" });
    } catch (failure) {
      if (generation !== listRequest.current || context !== currentContext.current) return;
      setRead({ context, status: "error" });
      setError(failure instanceof Error ? failure.message : "教学安排读取失败。");
    }
  }
  async function generate(newAttempt: boolean) {
    const body = !newAttempt && attempt ? attempt : {
      evidence_id: evidence.id, expected_evidence_revision: evidence.revision, idempotency_key: crypto.randomUUID(),
    };
    setAttempt(body); setBusy(true); setError(""); setNotice("");
    try {
      const incoming = await plansApi.generate(classroomId, body);
      if (context !== currentContext.current) return;
      setResults((previous) => {
        const existing = previous.find((result) => result.task.id === incoming.task.id);
        const merged = mergePlans(existing, incoming);
        return existing ? previous.map((item) => item.task.id === incoming.task.id ? merged : item)
          : [...previous, merged];
      });
      setSelectedTask(incoming.task.id);
      setNotice(taskNames[incoming.task.status]);
      await refresh();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "教学安排生成请求失败。"); }
    finally { setBusy(false); }
  }
  function updateRecord(updated: PlanRecord) {
    setResults((previous) => previous.map((item) => item.plan?.id === updated.id
      ? mergePlans(item, { ...item, plan: updated }) : item));
  }

  const disabled = busy || loading || !loaded || evidence.status !== "confirmed";
  return <section className="support-panel plans-panel" aria-label="教学安排与报告导出">
    <div hidden={view !== "teaching"}>
    <p className="eyebrow">已确认证据 → 教学支持</p><h3>提问与下一课安排</h3>
    <p className="panel-intro">模型初填提问、活动及检查方法；准备方式、备选安排和保留内容由教师补充。</p>
    {evidence.status !== "confirmed" && <p>须先确认有效学习证据，才能生成教学安排。</p>}
    <button className="primary-button" disabled={disabled} onClick={() => void generate(false)}>
      {attempt ? "重试同一次教学安排请求" : "生成提问与下一课安排"}
    </button>
    {attempt && <button disabled={disabled} onClick={() => void generate(true)}>重新生成教学安排（新请求）</button>}
    {attempt && <p>本次请求依据证据版本 {attempt.expected_evidence_revision}。
      {attempt.expected_evidence_revision !== evidence.revision && "证据已变化；只有明确重新生成才使用新版本。"}</p>}
    </div>
    {view === "publishing" && <h3>教师报告与导出</h3>}
    {error && <p role="alert">{error} 列表未核实成功时旧安排仅供查看，不能创建报告；原请求保留。</p>}
    <p role="status" aria-live="polite">{loading ? "正在核实当前安排与任务…"
      : busy ? "正在请求教学安排，尚未确认成功…" : notice}</p>
    <button disabled={loading || busy} onClick={() => void refresh()}>
      {loading ? "正在读取…" : "刷新教学安排与任务"}</button>
    {(!loaded || evidence.status !== "confirmed") && <p className="completion-note">
      当前来源或列表尚未核实，安排只读，创建教师报告暂不可用。</p>}
    {loaded && results.length === 0 && <p>此证据尚无教学安排任务，请先到教学支持生成。</p>}
    {results.length > 0 && <label>选择教学安排任务<select value={selectedTask}
      onChange={(event) => setSelectedTask(event.target.value)}>
      {results.map((result, index) => <option key={result.task.id} value={result.task.id}>
        安排任务 {index + 1} · {result.task.id.slice(-6)} · {taskNames[result.task.status]}
        {result.plan ? ` · 安排版本 ${result.plan.revision}` : ""}</option>)}
    </select></label>}
    {results.map((result, index) => <article className="task-card" key={result.task.id}
      hidden={result.task.id !== selectedTask} aria-label={`安排任务 ${index + 1} · ${result.task.id.slice(-6)}`}>
      <p><span className={`status-badge status-${result.task.status}`}>{taskNames[result.task.status]}</span>
        <span className="basis-label">依据证据版本 {result.task.basis.revision}</span></p>
      <details className="audit-details"><summary>生成任务记录</summary><p>任务编号：{result.task.id}</p></details>
      {result.task.error && <p role="alert">{result.task.error}</p>}
      {result.task.discarded_draft && <p>过期返回已丢弃，仅留审计记录，未采用为有效教学安排。</p>}
      {result.plan ? <>
        <div hidden={view !== "teaching"}>
        <PlanReview classroomId={classroomId} record={publicationRecord(
          result.plan, classroomId, evidence, read, result.task.status,
        )} onSaved={updateRecord} />
        </div><div hidden={view !== "publishing"}>
        <ExportPanel classroomId={classroomId} plan={publicationRecord(
          result.plan, classroomId, evidence, read, result.task.status,
        )} />
        </div>
      </>
        : <p>此任务没有可供教师核验的教学安排。</p>}
    </article>)}
  </section>;
}
