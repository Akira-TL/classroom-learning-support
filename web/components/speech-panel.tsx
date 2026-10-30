"use client";

import { useEffect, useState } from "react";
import type { Classroom } from "../lib/types";
import { phaseNames, simulationEvents, sourceNames, speech, statusNames } from "../lib/speech";
import type { SpeechEvent, Utterance } from "../lib/speech";
import { UtteranceReview } from "./utterance-review";

export function SpeechPanel({ classroom }: { classroom: Classroom }) {
  const [timeline, setTimeline] = useState<Utterance[]>([]);
  const [events, setEvents] = useState<SpeechEvent[]>([]);
  const [plan, setPlan] = useState<SpeechEvent[]>([]);
  const [index, setIndex] = useState(0);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function refresh() {
    const [nextTimeline, nextEvents] = await Promise.all([
      speech.timeline(classroom.id), speech.events(classroom.id),
    ]);
    setTimeline(nextTimeline); setEvents(nextEvents);
  }

  useEffect(() => {
    let active = true;
    Promise.all([speech.timeline(classroom.id), speech.events(classroom.id)])
      .then(([nextTimeline, nextEvents]) => {
        if (active) { setTimeline(nextTimeline); setEvents(nextEvents); }
      }).catch((failure: unknown) => {
        if (active) setError(failure instanceof Error ? failure.message : "语音记录读取失败。");
      });
    return () => { active = false; };
  }, [classroom.id]);

  useEffect(() => {
    if (!running || busy || index >= plan.length) return;
    const timer = setTimeout(async () => {
      setBusy(true); setError("");
      try {
        const receipt = await speech.receive(classroom.id, plan[index]);
        await refresh();
        setNotice(receipt.created ? `已接收第 ${index + 1} 个模拟步骤。` : "重复事件已去重，没有新增发言。");
        setIndex(index + 1);
        if (index + 1 >= plan.length) { setRunning(false); setNotice("模拟事件回放完成。"); }
      } catch (failure) {
        setRunning(false);
        setError(failure instanceof Error ? failure.message : "模拟事件发送失败。");
      } finally { setBusy(false); }
    }, 1800);
    return () => clearTimeout(timer);
  }, [running, busy, index, plan, classroom.id]);

  async function manualRefresh() {
    setBusy(true); setError("");
    try { await refresh(); setNotice("语音记录已重新读取。"); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "刷新失败。"); }
    finally { setBusy(false); }
  }

  return <section aria-label="语音结果与教师核验">
    <h3>模拟事件回放与教师核验</h3>
    <p>这里只回放合成事件，不采集麦克风、不调用真实语音服务。原音频可由教师另行授权归档。</p>
    <p>样例依次包含临时转写、定稿、重复事件、断流缺口、恢复、修订和结束。</p>
    <p>固定样例讨论平均分与四分之一；关联题目前请核对本课堂的题目与教学目标。</p>
    {error && <p role="alert">{error} 继续会使用同一事件标识重试，不会假装成功。</p>}
    <p role="status" aria-live="polite">{busy ? "正在发送或读取…" : notice}</p>
    <button disabled={busy || running} onClick={() => {
      setPlan(simulationEvents()); setIndex(0); setRunning(true); setError("");
      setNotice("开始新的模拟会话，既有会话不会被覆盖。");
    }}>开始新回放</button>
    <button disabled={!running} onClick={() => {
      setRunning(false); setNotice("回放已暂停；正在发送的步骤仍会完成。");
    }}>暂停</button>
    <button disabled={busy || running || index >= plan.length} onClick={() => setRunning(true)}>继续</button>
    <button disabled={busy} onClick={() => void manualRefresh()}>刷新时间线与事件</button>
    <p>进度：{index}/{plan.length}。暂停只控制模拟事件发送，不代表上游服务暂停。</p>
    {timeline.length === 0 && <p>暂无发言片段。</p>}
    {timeline.map((item) => <article key={`${item.session_id}/${item.segment_id}`}>
      <h4>{item.segment_id} · {phaseNames[item.phase]}</h4>
      <p>会话：{item.session_id}</p>
      <p>来源：{sourceNames[item.source_kind]}；匿名声源：{item.source_ref ?? "未提供"}；
        上游修订：{item.revision}；应用版本：{item.version}；
        时间：{item.start_ms}—{item.end_ms} 毫秒；{item.overlap ? "存在重叠" : "未标记重叠"}</p>
      <p>上游原文：{item.upstream_text}</p>
      <p>教师修订：{item.teacher_text ?? "未修订"}；核验人：{item.reviewed_by ?? "未核验"}</p>
      <UtteranceReview classroom={classroom} utterance={item} onSaved={refresh} />
    </article>)}
    <details><summary>已保存事件与接收缺口（{events.length} 条）</summary>
      <p>缺失区间只表示未收到完整数据，不代表学生沉默。</p>
      <ul>{events.map((item) => <li key={`${item.session_id}/${item.event_id}`}>
        会话 {item.session_id}；序号 {item.sequence}；
        {item.event_type === "status" || item.event_type === "end"
          ? item.status ? statusNames[item.status] : "结束事件"
          : phaseNames[item.event_type]}；来源：{sourceNames[item.source_kind]}
        {item.gap_start_ms !== null && <>；缺失区间 {item.gap_start_ms}—{item.gap_end_ms} 毫秒</>}
      </li>)}</ul>
    </details>
  </section>;
}
