"use client";

import { useEffect, useState } from "react";
import { taskNames } from "../../lib/evidence";
import type { EvidenceRecord } from "../../lib/evidence";
import { mergePlans, plansApi } from "../../lib/plans";
import type { GeneratePlan, PlanRecord, PlanResult } from "../../lib/plans";
import { PlanReview } from "./review";
import { ExportPanel } from "../exports/panel";

export function PlanPanel({ classroomId, evidence }: { classroomId: string; evidence: EvidenceRecord }) {
  const [results, setResults] = useState<PlanResult[]>([]);
  const [attempt, setAttempt] = useState<GeneratePlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function accept(incoming: PlanResult[]) {
    const matched = incoming.filter((item) => item.task.request.evidence_id === evidence.id);
    setResults((previous) => matched.map((item) => mergePlans(
      previous.find((result) => result.task.id === item.task.id), item,
    )));
    setAttempt((previous) => previous ?? matched.at(-1)?.task.request ?? null);
    setLoaded(true);
  }
  useEffect(() => {
    let active = true; setLoading(true);
    plansApi.list(classroomId).then((incoming) => { if (active) accept(incoming); })
      .catch((failure: unknown) => {
        if (active) setError(failure instanceof Error ? failure.message : "教学安排读取失败。");
      }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [classroomId, evidence.id, evidence.revision, evidence.status]);

  async function refresh() {
    setLoading(true); setError("");
    try { accept(await plansApi.list(classroomId)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "教学安排读取失败。"); }
    finally { setLoading(false); }
  }
  async function generate(newAttempt: boolean) {
    const body = !newAttempt && attempt ? attempt : {
      evidence_id: evidence.id, expected_evidence_revision: evidence.revision, idempotency_key: crypto.randomUUID(),
    };
    setAttempt(body); setBusy(true); setError(""); setNotice("");
    try {
      const incoming = await plansApi.generate(classroomId, body);
      setResults((previous) => {
        const existing = previous.find((result) => result.task.id === incoming.task.id);
        const merged = mergePlans(existing, incoming);
        return existing ? previous.map((item) => item.task.id === incoming.task.id ? merged : item)
          : [...previous, merged];
      });
      setNotice(taskNames[incoming.task.status]);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "教学安排生成请求失败。"); }
    finally { setBusy(false); }
  }
  function updateRecord(updated: PlanRecord) {
    setResults((previous) => previous.map((item) => item.plan?.id === updated.id
      ? mergePlans(item, { ...item, plan: updated }) : item));
  }

  const disabled = busy || loading || !loaded || evidence.status !== "confirmed";
  return <section aria-label="提问与下一课安排生成">
    <h5>提问安排与下一课调整</h5>
    <p>点击才调用 DeepSeek。模型初填提问、活动及检查方法；准备方式、备选安排和保留内容需教师补充。</p>
    {evidence.status !== "confirmed" && <p>须先确认有效学习证据，才能生成教学安排。</p>}
    {error && <p role="alert">{error} 重试同一请求不会创建新任务；重新生成须明确点击。</p>}
    <p role="status" aria-live="polite">{busy ? "正在请求教学安排，尚未确认成功…" : notice}</p>
    <button disabled={disabled} onClick={() => void generate(false)}>
      {attempt ? "重试同一次教学安排请求" : "生成提问与下一课安排"}
    </button>
    {attempt && <button disabled={disabled} onClick={() => void generate(true)}>重新生成教学安排（新请求）</button>}
    <button disabled={loading} onClick={() => void refresh()}>{loading ? "正在读取…" : "刷新教学安排与任务"}</button>
    {attempt && <p>本次请求依据证据版本 {attempt.expected_evidence_revision}。
      {attempt.expected_evidence_revision !== evidence.revision && "证据已变化；只有明确重新生成才使用新版本。"}</p>}
    {!loading && results.length === 0 && <p>此证据尚无教学安排任务。</p>}
    {results.map((result) => <article key={result.task.id}>
      <p>安排任务 {result.task.id}：{taskNames[result.task.status]}；依据证据版本 {result.task.basis.revision}</p>
      {result.task.error && <p role="alert">{result.task.error}</p>}
      {result.task.discarded_draft && <p>过期返回已丢弃，仅留审计记录，未采用为有效教学安排。</p>}
      {result.plan ? <>
        <PlanReview classroomId={classroomId} record={result.plan} onSaved={updateRecord} />
        <ExportPanel classroomId={classroomId} plan={result.plan} />
      </>
        : <p>此任务没有可供教师核验的教学安排。</p>}
    </article>)}
  </section>;
}
