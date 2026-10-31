"use client";

import { useEffect, useState } from "react";
import { speech, type Utterance } from "../../lib/speech";
import type { Observation } from "../../lib/care/types";
import { AudioPanel } from "../audio-panel";
import styles from "./care.module.css";

export function CareObservation({ item, active }: { item: Observation; active: boolean }) {
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState<Utterance | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    let active = true;
    speech.timeline(item.classroom_id).then((items) => {
      if (!active) return;
      const utterance = items.find((entry) => entry.session_id === item.session_id
        && entry.segment_id === item.segment_id && entry.version === item.expected_utterance_version);
      setSource(utterance ?? null);
      if (!utterance) setError("来源版本已变化，当前观察需要重新核验。");
    }).catch((failure: unknown) => {
      if (active) setError(failure instanceof Error ? failure.message : "无法读取关联发言。");
    });
    return () => { active = false; };
  }, [open, item.classroom_id, item.session_id, item.segment_id, item.expected_utterance_version]);
  return <article className={styles.observation}>
    <time>{item.observed_on}</time><p>{item.fact}</p>
    <p className={styles.muted}>采集条件：{item.capture_conditions}</p>
    {item.teacher_note && <p>教师观察：{item.teacher_note}</p>}
    {item.measurements ? <p>上游测量：
      {item.measurements.pitch_hz !== null && <>基频 {item.measurements.pitch_hz} Hz；</>}
      {item.measurements.level_dbfs !== null && <>电平 {item.measurements.level_dbfs} dBFS；</>}
      方法：{item.measurements.method}</p> : <p className={styles.muted}>{item.measurement_note}</p>}
    <span className={styles.badge}>{item.source_current ? item.confirmed ? "教师已确认" : "待确认" : "来源已变化"}</span>
    <button type="button" onClick={() => setOpen(!open)}>{open ? "收起原声" : "回听原声与处理音轨"}</button>
    {open && <>{error && <p role="status">{error}</p>}{source && <AudioPanel classroomId={item.classroom_id}
      utterance={source} active={open && active} onSaved={async () => {}} />}</>}
  </article>;
}
