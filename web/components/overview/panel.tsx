"use client";

import { useEffect, useState } from "react";
import { getAdminSummary } from "../../lib/overview";
import type { AdminSummary, CountRatio } from "../../lib/overview";

function displayRatio(value: CountRatio): string {
  return value.ratio === null ? `未定义（${value.numerator}/${value.denominator}，分母为0）`
    : `${value.numerator}/${value.denominator}（${(value.ratio * 100).toFixed(1)}%）`;
}

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
      <p>快照时间（北京时间）：{new Date(summary.snapshot_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}</p>
      <p>{summary.time_range}</p>
      <dl>
        <dt>授权课堂数</dt><dd>{summary.classroom_count}</dd>
        <dt>相关后续检查记录</dt><dd>{summary.observation_count}</dd>
      </dl>
      <h3>生成、确认与采用分别统计</h3>
      <div className="table-scroll"><table>
        <thead><tr><th>来源与类型</th><th>有效生成／人工录入</th><th>已确认</th><th>已采用</th>
          <th>确认率（确认÷前项）</th><th>采用率（采用÷确认）</th></tr></thead>
        <tbody>{([
          { label: "模型生成教学安排", initial: summary.plan_metrics.generated_count, values: summary.plan_metrics },
          { label: "模型生成证据驱动练习", initial: summary.exercise_metrics.generated_count,
            values: summary.exercise_metrics },
          { label: "教师人工通用练习（仅录入，不是模型生成）", initial: summary.manual_exercise_metrics.recorded_count,
            values: summary.manual_exercise_metrics },
        ]).map((row) => <tr key={row.label}>
          <th>{row.label}</th><td>{row.initial}</td><td>{row.values.confirmed_count}</td>
          <td>{row.values.adopted_count}</td>
          <td>{displayRatio(row.values.confirmation_rate)}</td><td>{displayRatio(row.values.adoption_rate)}</td>
        </tr>)}</tbody>
      </table></div>
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
