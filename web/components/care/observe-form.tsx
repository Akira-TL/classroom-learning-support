"use client";

import { useEffect, useState, type FormEvent } from "react";
import type { Classroom } from "../../lib/types";
import type { Utterance } from "../../lib/speech";
import { careApi } from "../../lib/care/api";
import { segmentKey, timeLabel } from "../workspace/types";
import styles from "./care.module.css";

export function ObserveForm({ classroom, student, items, onSaved }: {
  classroom: Classroom; student: string; items: Utterance[]; onSaved: () => Promise<void>;
}) {
  const sources = items.filter((item) => item.student_alias === student && ["final", "revision"].includes(item.phase)
    && [item.text_review, item.identity_review, item.question_review].every((review) => review === "confirmed"));
  const [selected, setSelected] = useState("");
  const source = sources.find((item) => segmentKey(item) === selected) ?? sources[0];
  const [fact, setFact] = useState("");
  const [conditions, setConditions] = useState("");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => { setConfirmed(false); }, [source?.session_id, source?.segment_id, source?.version]);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!source || busy) return;
    setBusy(true); setMessage("");
    try {
      await careApi.observe(classroom.id, { session_id: source.session_id, segment_id: source.segment_id,
        expected_utterance_version: source.version, student_id: student, observed_on: classroom.date,
        fact, capture_conditions: conditions, teacher_note: note, confirmed });
      setMessage("观察记录已保存。"); await onSaved();
    } catch (failure) { setMessage(failure instanceof Error ? failure.message : "观察保存未确认成功。"); }
    finally { setBusy(false); }
  }
  return <details className={styles.card}><summary>记录当前课堂的声音观察</summary>
    <p className={styles.muted}>成人模拟资料演示。记录可核查事实与教师观察，声学测量由上游提供。</p>
    {sources.length === 0 ? <p>该学生尚无完成三项核验的发言，请先在课堂分析中核验学生归属与原话。</p>
      : <form onSubmit={(event) => void submit(event)}><fieldset disabled={busy}>
        <label>依据发言<select value={source ? segmentKey(source) : ""}
          onChange={(event) => setSelected(event.target.value)}>
          {sources.map((item) => <option key={segmentKey(item)} value={segmentKey(item)}>
            {timeLabel(item.start_ms)} · {item.teacher_text ?? item.upstream_text}</option>)}
        </select></label><p>观察日期：{classroom.date}（与来源课堂日期一致）</p>
        <label>可核查事实<textarea required maxLength={3000} value={fact}
          onChange={(event) => setFact(event.target.value)} placeholder="例如：本次回答中有两次停顿；可回听核查。" /></label>
        <label>采集条件<input required maxLength={1000} value={conditions}
          onChange={(event) => setConditions(event.target.value)} placeholder="设备、距离、音量设置与环境噪声" /></label>
        <label>教师观察与核验限制<textarea maxLength={3000} value={note}
          onChange={(event) => setNote(event.target.value)} /></label>
        <label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
          我已回听并核对上述事实与来源</label>
        <button type="submit">{busy ? "保存中…" : "保存观察记录"}</button>
      </fieldset></form>}
    {message && <p role="status">{message}</p>}
  </details>;
}
