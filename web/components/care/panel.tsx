"use client";

import { useCallback, useEffect, useState } from "react";
import type { Classroom } from "../../lib/types";
import { speech, type Utterance } from "../../lib/speech";
import { careApi } from "../../lib/care/api";
import { sameComparisonScope, weekPeriods } from "../../lib/care/periods";
import type { CareReport, Comparison, Observation } from "../../lib/care/types";
import { CareObservation } from "./observation";
import { ObserveForm } from "./observe-form";
import { CareReportEditor } from "./report-editor";
import { PendingObservations } from "./pending";
import styles from "./care.module.css";

const dateLabels: Record<string, string> = {
  baseline_start: "上期开始", baseline_end: "上期结束", current_start: "本期开始", current_end: "本期结束",
};

function CareStudent({ classroom, student, active }: { classroom: Classroom; student: string; active: boolean }) {
  const [periods, setPeriods] = useState(() => weekPeriods(new Date().toLocaleDateString("sv-SE")));
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [reports, setReports] = useState<CareReport[]>([]);
  const [items, setItems] = useState<Utterance[]>([]);
  const [pending, setPending] = useState<Observation[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const request = { student_id: student, ...periods };
  const current = comparison && sameComparisonScope(comparison.periods, request) ? comparison : null;
  useEffect(() => {
    if (!active) return;
    let cancelled = false; setLoading(true); setError("");
    Promise.all([careApi.compare({ student_id: student, ...periods }), careApi.reports(classroom.id),
      speech.timeline(classroom.id), careApi.observations(classroom.id)])
      .then(([incoming, list, timeline, observations]) => {
      if (!cancelled) {
        setComparison(incoming); setReports(list.filter((report) => report.student_id === student)); setItems(timeline);
        setPending(observations.filter((item) => item.student_id === student
          && (!item.confirmed || !item.source_current)));
      }
    }).catch((failure: unknown) => {
      if (!cancelled) { setComparison(null); setReports([]);
        setError(failure instanceof Error ? failure.message : "观察读取失败。"); }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [classroom.id, student, periods, active, refresh]);
  const reload = useCallback(async () => { setRefresh((value) => value + 1); }, []);
  return <div className={styles.body}>
    <section className={styles.card}><div className={styles.actions}><h2>{student} · 声音观察</h2>
      <button type="button" disabled={loading} onClick={() => void reload()}>刷新记录</button></div>
      <p className={styles.muted}>成人模拟资料演示 · 上周与本周的已确认课堂观察</p>
      <details><summary>调整比较日期</summary><div className={styles.periods}>
        {Object.entries(periods).map(([key, value]) => <label key={key}>
          {dateLabels[key]}
          <input type="date" value={value}
            onChange={(event) => setPeriods({ ...periods, [key]: event.target.value })} />
        </label>)}
      </div></details>
      {loading && <p role="status">正在核对观察来源…</p>}{error && <p role="alert">{error}</p>}
    </section>
    <div className={styles.periods}>{[
      { title: "上周观察", start: periods.baseline_start, end: periods.baseline_end, values: current?.baseline ?? [] },
      { title: "本周观察", start: periods.current_start, end: periods.current_end, values: current?.current ?? [] },
    ].map((period) => <section className={styles.card} key={period.title}><h2>{period.title}</h2>
      <p className={styles.muted}>{period.start} — {period.end}</p>
      {period.values.length === 0 && <p>该时段尚无来源有效且经教师确认的观察。</p>}
      {period.values.map((item) => <CareObservation key={`${item.id}/${item.revision}`} item={item} active={active} />)}
    </section>)}</div>
    <section className={styles.card}><h2>变化与核验限制</h2>
      {current ? <><table className={styles.metrics}><thead><tr>
        <th>测量</th><th>上周</th><th>本周</th><th>变化</th></tr></thead>
        <tbody>{current.metrics.map((metric) => <tr key={metric.name}>
          <td>{metric.name === "pitch_hz" ? "基频" : "音频电平"}（{metric.unit}）</td>
          <td>{metric.baseline_mean?.toFixed(2) ?? "缺少测量"}</td>
          <td>{metric.current_mean?.toFixed(2) ?? "缺少测量"}</td>
          <td>{metric.comparable ? metric.difference?.toFixed(2) : "条件不足，不比较"}</td>
        </tr>)}</tbody></table>
        {current.metrics.map((metric) => <p className={styles.muted} key={metric.name}>{metric.explanation}</p>)}
        {current.notes.map((note, index) => <p key={index}>{note}</p>)}</>
        : <p>获取有效的两期观察后，在此比较有明确方法和采集条件的测量。</p>}
    </section>
    <ObserveForm classroom={classroom} student={student} items={items} onSaved={reload} />
    <PendingObservations items={pending} active={active} onSaved={reload} />
    <CareReportEditor classroomId={classroom.id} comparison={current} reports={reports} onSaved={reload} />
  </div>;
}

export function CarePanel({ classroom, active = true }: { classroom: Classroom; active?: boolean }) {
  const [selected, setSelected] = useState(classroom.students[0] ?? "");
  return <section className={styles.page} aria-label="学生关怀"><header className={styles.heading}>
    <h1>学生关怀</h1><p>{classroom.title} · 基于原话与教师观察，安排后续交流和学习支持。</p>
  </header><div className={styles.layout}><nav className={styles.roster} aria-label="选择观察学生">
    {classroom.students.map((student) => <button key={student} type="button" aria-pressed={student === selected}
      onClick={() => setSelected(student)}>{student}</button>)}
  </nav><div>{classroom.students.map((student) => <div key={student} hidden={student !== selected}>
    <CareStudent classroom={classroom} student={student} active={active && student === selected} />
  </div>)}</div></div></section>;
}
