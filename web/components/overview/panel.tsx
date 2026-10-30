"use client";

import { useEffect, useState } from "react";
import { getAdminSummary } from "../../lib/overview";
import type { AdminSummary } from "../../lib/overview";

export function AdminOverview() {
  const [summary, setSummary] = useState<AdminSummary | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    getAdminSummary().then((result) => { if (active) setSummary(result); })
      .catch((failure: unknown) => {
        if (active) setError(failure instanceof Error ? failure.message : "教学支持汇总读取失败。");
      }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, []);
  async function refresh() {
    setBusy(true); setError("");
    try { setSummary(await getAdminSummary()); }
    catch (failure) {
      setSummary(null); setError(failure instanceof Error ? failure.message : "教学支持汇总读取失败。");
    } finally { setBusy(false); }
  }

  return <section aria-label="管理者教学支持汇总">
    <h2>教学支持汇总</h2>
    {error && <p role="alert">{error}</p>}
    <p role="status">{busy ? "正在读取授权汇总…" : ""}</p>
    <button disabled={busy} onClick={() => void refresh()}>刷新汇总</button>
    {summary && <>
      <p>{summary.scope}</p>
      <dl>
        <dt>授权课堂数</dt><dd>{summary.classroom_count}</dd>
        <dt>当前已采用教学安排</dt><dd>{summary.adopted_plan_count}</dd>
        <dt>当前已采用练习组</dt><dd>{summary.adopted_exercise_count}</dd>
        <dt>相关后续检查记录</dt><dd>{summary.observation_count}</dd>
      </dl>
      <h3>资源需求</h3>
      <ul>{summary.resource_needs.map((item) => <li key={item.kind}>{item.description}：{item.count}</li>)}</ul>
      <h3>学生相关整体数量</h3>
      <p>{summary.explanation}</p>
      {summary.performance_state === "available" && <dl>
        <dt>有效已确认证据条数</dt><dd>{summary.confirmed_evidence_count}</dd>
        <dt>不同学生数</dt><dd>{summary.observed_student_count}</dd>
      </dl>}
      <p>{summary.counting_rule}</p>
    </>}
  </section>;
}
