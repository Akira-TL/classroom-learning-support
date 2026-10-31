"use client";

import { useEffect, useState } from "react";
import { careApi } from "../../lib/care/api";
import type { RecipientReport } from "../../lib/care/types";
import styles from "./care.module.css";

export function CareReader({ audience }: { audience: "student" | "parent" }) {
  const [reports, setReports] = useState<RecipientReport[]>([]);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      try {
        const incoming = await careApi.mine();
        if (!cancelled) { setReports(incoming.filter((item) => item.audience === audience)); setError(""); }
      } catch (failure) {
        if (!cancelled) { setReports([]); setError(failure instanceof Error ? failure.message : "关怀反馈读取失败。"); }
      }
      if (!cancelled) timer = setTimeout(() => void load(), 10000);
    }
    void load(); return () => { cancelled = true; clearTimeout(timer); };
  }, [audience, refresh]);
  return <section className={`${styles.card} ${styles.reader}`} aria-label="教师关怀反馈">
    <h2>{audience === "student" ? "老师的关怀与跟进" : "孩子的关怀与跟进"}</h2>
    <p className={styles.muted}>成人模拟资料演示 · 仅展示教师已发布给当前账号的文字反馈。</p>
    <button type="button" onClick={() => setRefresh((value) => value + 1)}>刷新关怀反馈</button>
    {error && <p role="alert">{error}</p>}
    {reports.length === 0 && <p>暂无已发布的关怀反馈。</p>}
    {reports.map((report) => <article key={report.id}><span className={styles.badge}>教师已发布 · 版本 {report.revision}</span>
      <p>{report.text}</p></article>)}
  </section>;
}
