"use client";

import { useEffect, useState } from "react";
import type { Classroom } from "../../../lib/types";
import { labelsApi } from "../../../lib/care/labels/api";
import { sameComparisonScope, weekPeriods } from "../../../lib/care/periods";
import { perspectives, tagNames, type AutoExplanation, type Perspective,
  type TagComparison } from "../../../lib/care/labels/types";
import { countLabel, minuteRate } from "../../../lib/care/labels/presentation";
import { LabelImport } from "./import";
import { LabelPeriod } from "./period";
import { AutomaticReport } from "./explanation";
import common from "../care.module.css";
import styles from "./labels.module.css";

const dateLabels: Record<string, string> = {
  baseline_start: "上周开始", baseline_end: "上周结束", current_start: "本周开始", current_end: "本周结束",
};
export function LabelDashboard({ classroom, student, active, initialPerspective = "teacher" }: {
  classroom: Classroom; student: string; active: boolean; initialPerspective?: Perspective;
}) {
  const [periods, setPeriods] = useState(() => weekPeriods(new Date().toLocaleDateString("sv-SE")));
  const [comparison, setComparison] = useState<TagComparison | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [perspective, setPerspective] = useState<Perspective>(initialPerspective);
  const [explanation, setExplanation] = useState<AutoExplanation | null>(null);
  const [reportError, setReportError] = useState("");
  const [generating, setGenerating] = useState(false);
  const request = { student_id: student, ...periods };
  const current = comparison && sameComparisonScope(comparison.periods, request) ? comparison : null;
  const hasData = Boolean(current && (current.baseline.length > 0 || current.current.length > 0));
  const sourceKey = [...current?.baseline ?? [], ...current?.current ?? []]
    .map((batch) => `${batch.id}/${batch.revision}/${batch.audio_asset?.id ?? "no-audio"}`).join(";");
  useEffect(() => {
    setExplanation(null); setReportError("");
    if (!active || !sourceKey) { setGenerating(false); return; }
    let cancelled = false; setGenerating(true);
    labelsApi.explain(classroom.id, { student_id: student, ...periods }, perspective).then((result) => {
      if (!cancelled) setExplanation(result);
    }).catch((failure: unknown) => {
      if (!cancelled) setReportError(failure instanceof Error ? failure.message : "自动解释暂时不可用。");
    }).finally(() => { if (!cancelled) setGenerating(false); });
    return () => { cancelled = true; };
  }, [active, classroom.id, student, periods, perspective, sourceKey, refresh]);
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
    <section className={common.card}><div className={common.actions}>
      <h2>学生{student.replace(/^student-/, "")} · 历史标签与变化</h2>
      <button type="button" onClick={() => setRefresh((value) => value + 1)}>刷新数据</button>
    </div><p>按所提供的标签与时间戳查看历史变化。</p>
    <details><summary>选择上周、本周日期</summary><div className={common.periods}>
      {Object.entries(periods).map(([key, value]) => <label key={key}>{dateLabels[key]}
        <input type="date" value={value} onChange={(event) => setPeriods({ ...periods, [key]: event.target.value })} />
      </label>)}
    </div></details>{error && <p role="alert">{error}</p>}</section>
    {current && !hasData && <section className={`${common.card} ${styles.empty}`}><h2>等待导入标签</h2>
      <p>导入所选学生的标签、时间戳和对应会话后，将显示上周与本周的变化。尚无数据不表示零次。</p>
      <LabelImport classroomId={classroom.id} student={student} onSaved={() => setRefresh((value) => value + 1)} />
    </section>}
    {!current && !error && <p role="status">正在读取标签记录…</p>}
    {hasData && <LabelImport classroomId={classroom.id} student={student}
      onSaved={() => setRefresh((value) => value + 1)} />}
    {!current && error && <LabelImport classroomId={classroom.id} student={student}
      onSaved={() => setRefresh((value) => value + 1)} />}
    <section className={common.card}><h2>报告视角</h2>
      <div className={styles.perspectives} role="group" aria-label="切换报告预览视角">
        {perspectives.map(([value, label]) => <button type="button" key={value} aria-pressed={perspective === value}
          onClick={() => setPerspective(value)}>{label}</button>)}
      </div><p className={common.muted}>教师预览不同对象的解释，实际学生与家长账号只访问本人或绑定孩子的报告。</p>
    </section>
    {hasData && current && current.summaries.length > 0 && <div className={styles.summary}>
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
    </div>}
    {hasData && <div className={styles.periods}>
      <LabelPeriod title="上周时间分布" batches={current?.baseline ?? []} active={active}
        allowAudio={perspective !== "teaching_director"} onSaved={() => setRefresh((value) => value + 1)} />
      <LabelPeriod title="本周时间分布" batches={current?.current ?? []} active={active}
        allowAudio={perspective !== "teaching_director"} onSaved={() => setRefresh((value) => value + 1)} />
    </div>}
    {hasData && current?.notes.map((note, index) => <p className={common.muted} key={index}>{note}</p>)}
    {generating && <section className={common.card}><p role="status">正在根据当前标签自动生成解释…</p></section>}
    {reportError && <section className={common.card}><p role="alert">{reportError}</p>
      <button type="button" onClick={() => setRefresh((value) => value + 1)}>重试读取与解释</button></section>}
    {explanation && explanation.perspective === perspective && <AutomaticReport result={explanation} />}
  </div>;
}
