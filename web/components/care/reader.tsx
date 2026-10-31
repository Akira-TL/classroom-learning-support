"use client";

import { useEffect, useState } from "react";
import { labelsApi } from "../../lib/care/labels/api";
import { weekPeriods } from "../../lib/care/periods";
import type { RecipientExplanation } from "../../lib/care/labels/types";
import { AutomaticReport } from "./labels/explanation";
import styles from "./care.module.css";

export function CareReader({ audience, studentId }: { audience: "student" | "parent"; studentId: string }) {
  const [result, setResult] = useState<RecipientExplanation | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [periods, setPeriods] = useState(() => weekPeriods(new Date().toLocaleDateString("sv-SE")));
  useEffect(() => {
    if (!studentId) { setError("当前账号尚未绑定学生，无法读取学生信息。"); return; }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setResult(null);
    async function load() {
      setLoading(true);
      try {
        const incoming = await labelsApi.mine({ student_id: studentId, ...periods }, audience);
        if (!cancelled) {
          setResult(incoming.student_id === studentId && incoming.perspective === audience ? incoming : null);
          setError("");
        }
      } catch (failure) {
        if (!cancelled) { setResult(null);
          setError(failure instanceof Error ? failure.message : "自动报告读取失败。"); }
      } finally { if (!cancelled) setLoading(false); }
      if (!cancelled) timer = setTimeout(() => void load(), 10000);
    }
    void load(); return () => { cancelled = true; clearTimeout(timer); };
  }, [studentId, audience, periods, refresh]);
  return <section className={`${styles.card} ${styles.reader}`} aria-label="学生信息自动报告">
    <h2>{audience === "student" ? "我的课堂信息" : "孩子的课堂信息"}</h2>
    <details><summary>比较日期</summary><div className={styles.periods}>
      <label>上期开始<input type="date" value={periods.baseline_start}
        onChange={(event) => setPeriods({ ...periods, baseline_start: event.target.value })} /></label>
      <label>上期结束<input type="date" value={periods.baseline_end}
        onChange={(event) => setPeriods({ ...periods, baseline_end: event.target.value })} /></label>
      <label>本期开始<input type="date" value={periods.current_start}
        onChange={(event) => setPeriods({ ...periods, current_start: event.target.value })} /></label>
      <label>本期结束<input type="date" value={periods.current_end}
        onChange={(event) => setPeriods({ ...periods, current_end: event.target.value })} /></label>
    </div></details>
    <button type="button" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>刷新自动报告</button>
    {loading && <p role="status">正在读取当前资料并生成解释…</p>}
    {error && <p role="status">{error}</p>}
    {result && <AutomaticReport result={result} />}
  </section>;
}
