"use client";

import { useEffect, useState } from "react";
import type { Classroom } from "../../../lib/types";
import { labelsApi } from "../../../lib/care/labels/api";
import { sameComparisonScope, weekPeriods } from "../../../lib/care/periods";
import { tagNames, type TagComparison } from "../../../lib/care/labels/types";
import { countLabel, minuteRate } from "../../../lib/care/labels/presentation";
import { LabelImport } from "./import";
import { LabelPeriod } from "./period";
import common from "../care.module.css";
import styles from "./labels.module.css";

const dateLabels: Record<string, string> = {
  baseline_start: "上周开始", baseline_end: "上周结束", current_start: "本周开始", current_end: "本周结束",
};
export function LabelDashboard({ classroom, student, active }: {
  classroom: Classroom; student: string; active: boolean;
}) {
  const [periods, setPeriods] = useState(() => weekPeriods(new Date().toLocaleDateString("sv-SE")));
  const [comparison, setComparison] = useState<TagComparison | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const request = { student_id: student, ...periods };
  const current = comparison && sameComparisonScope(comparison.periods, request) ? comparison : null;
  useEffect(() => {
    if (!active) return;
    let cancelled = false; setComparison(null); setError("");
    labelsApi.compare({ student_id: student, ...periods }).then((value) => {
      if (!cancelled) setComparison(value);
    }).catch((failure: unknown) => {
      if (!cancelled) setError(failure instanceof Error ? failure.message : "标签比较读取失败。");
    });
    return () => { cancelled = true; };
  }, [student, periods, active, refresh]);
  return <div className={styles.detail}>
    <section className={common.card}><div className={common.actions}><h2>{student} · 历史标签与变化</h2>
      <button type="button" onClick={() => setRefresh((value) => value + 1)}>刷新数据</button>
    </div><p>比较用户提供的时间标注，不运行标签检测训练。外部状态标签保留其来源与待核实说明。</p>
    <details><summary>选择上周、本周日期</summary><div className={common.periods}>
      {Object.entries(periods).map(([key, value]) => <label key={key}>{dateLabels[key]}
        <input type="date" value={value} onChange={(event) => setPeriods({ ...periods, [key]: event.target.value })} />
      </label>)}
    </div></details>{error && <p role="alert">{error}</p>}</section>
    <LabelImport classroomId={classroom.id} student={student} onSaved={() => setRefresh((value) => value + 1)} />
    {current && current.summaries.length > 0 ? <div className={styles.summary}>
      {current.summaries.map((summary) => <article key={summary.label}><h3>{tagNames[summary.label]}</h3>
        <p>上周 <strong>{countLabel(summary.baseline_count)}</strong></p>
        <small>{minuteRate(summary.baseline_per_hour)}</small>
        <p>本周 <strong>{countLabel(summary.current_count)}</strong></p>
        <small>{minuteRate(summary.current_per_hour)}</small>
        <p>记录次数变化：{summary.count_difference === null ? "数据不足" : summary.count_difference > 0
          ? `增加 ${summary.count_difference} 次` : summary.count_difference < 0
            ? `减少 ${-summary.count_difference} 次` : "无变化"}</p>
        {summary.notes.map((note, index) => <p key={index}>{note}</p>)}
      </article>)}
    </div> : <section className={common.card}><h2>等待导入标签</h2>
      <p>提供上周与本周的标签、时间戳和对应会话后，这里将显示次数与时间分布。尚无数据不表示零次。</p></section>}
    <div className={styles.periods}>
      <LabelPeriod title="上周时间分布" batches={current?.baseline ?? []} active={active} allowAudio />
      <LabelPeriod title="本周时间分布" batches={current?.current ?? []} active={active} allowAudio />
    </div>
    {current?.notes.map((note, index) => <p className={common.muted} key={index}>{note}</p>)}
  </div>;
}
