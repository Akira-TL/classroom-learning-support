"use client";

import { useEffect, useRef, useState } from "react";
import type { Classroom } from "../lib/types";
import { phaseNames, simulationEvents, sourceNames, speech, statusNames } from "../lib/speech";
import type { SpeechEvent, Utterance } from "../lib/speech";
import { UtteranceReview } from "./utterance-review";
import { EvidencePanel } from "./evidence-panel";
import { CorrectionPanel } from "./corrections/panel";
import { ClassroomAnalysis } from "./workspace/analysis/panel";
import { SpeechRefreshState } from "./workspace/speech/refresh-state";
import { segmentKey, timeLabel } from "./workspace/types";
import type { WorkspaceView } from "./workspace/types";
import styles from "./workspace/workspace.module.css";

export function SpeechPanel({ classroom, view = "review", active = true, onViewChange }: {
  classroom: Classroom; view?: WorkspaceView; active?: boolean; onViewChange?: (view: WorkspaceView) => void;
}) {
  const [timeline, setTimeline] = useState<Utterance[]>([]);
  const [events, setEvents] = useState<SpeechEvent[]>([]);
  const [plan, setPlan] = useState<SpeechEvent[]>([]);
  const [index, setIndex] = useState(0);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selection, setSelection] = useState("");
  const refreshState = useRef(new SpeechRefreshState());
  refreshState.current.busy = busy;
  const [streamError, setStreamError] = useState("");
  const preferred = timeline.filter((item) => ["final", "revision"].includes(item.phase)
    && [item.text_review, item.identity_review, item.question_review].every((state) => state === "confirmed"))
    .at(-1) ?? timeline.at(-1);
  const selected = timeline.some((item) => segmentKey(item) === selection)
    ? selection : preferred ? segmentKey(preferred) : "";
  const current = timeline.find((item) => segmentKey(item) === selected);

  function select(item: Utterance) {
    setSelection(segmentKey(item));
    const anchor = `utterance-${item.session_id}-${item.segment_id}`;
    window.history.replaceState(null, "", `#${encodeURIComponent(anchor)}`);
  }

  function locate(item: Utterance) {
    select(item); onViewChange?.("review");
    requestAnimationFrame(() => {
      document.getElementById(`utterance-${item.session_id}-${item.segment_id}`)
        ?.scrollIntoView({ block: "center", behavior: "smooth" });
    });
  }

  useEffect(() => {
    function followSource() {
      let anchor = "";
      try { anchor = decodeURIComponent(window.location.hash.slice(1)); } catch { return; }
      const item = timeline.find((entry) => `utterance-${entry.session_id}-${entry.segment_id}` === anchor);
      if (item) setSelection(segmentKey(item));
    }
    function navigateSource() {
      followSource();
      let anchor = "";
      try { anchor = decodeURIComponent(window.location.hash.slice(1)); } catch { return; }
      if (timeline.some((entry) => `utterance-${entry.session_id}-${entry.segment_id}` === anchor)) {
        onViewChange?.("review");
        requestAnimationFrame(() => document.getElementById(anchor)?.scrollIntoView({ block: "center" }));
      }
    }
    followSource(); window.addEventListener("hashchange", navigateSource);
    return () => window.removeEventListener("hashchange", navigateSource);
  }, [timeline, onViewChange]);

  async function refresh() {
    const sequence = refreshState.current.begin();
    const [nextTimeline, nextEvents] = await Promise.all([
      speech.timeline(classroom.id), speech.events(classroom.id),
    ]);
    if (refreshState.current.accepts(sequence)) {
      setTimeline(nextTimeline); setEvents(nextEvents);
    }
  }

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      if (refreshState.current.busy) {
        timer = setTimeout(() => void poll(), 2000); return;
      }
      try {
        await refresh();
        if (!cancelled) setStreamError("");
      } catch (failure) {
        if (!cancelled) setStreamError(failure instanceof Error ? failure.message : "语音记录读取失败。");
      }
      if (!cancelled) timer = setTimeout(() => void poll(), 2000);
    }
    void poll();
    return () => { cancelled = true; refreshState.current.invalidate(); clearTimeout(timer); };
  }, [classroom.id, active]);

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

  const title = { review: "核验工作台", teaching: "教学支持", publishing: "发布与反馈" }[view];
  return <section className={styles.root} aria-label="语音结果与教师核验">
    <header className={styles.toolbar}><h2 className={styles.srOnly}>{title}</h2>
      <p role="status" aria-live="polite">{busy ? "正在发送或读取…" : notice || "原话可追溯 · 教师核验后使用"}</p>
      <button disabled={busy} onClick={() => void manualRefresh()}>刷新来源</button>
    </header>
    {error && <p role="alert">{error} 继续会使用同一事件标识重试，不会假装成功。</p>}
    {streamError && <p role="status">{streamError} 正在自动重连，当前保留上次收到的记录。</p>}
    <div hidden={view === "review"} className={styles.selection}>
      <label>当前发言<select value={selected} onChange={(event) => {
        const item = timeline.find((entry) => segmentKey(entry) === event.target.value);
        if (item) select(item);
      }}><option value="" disabled>尚无发言片段</option>
        {timeline.map((item, index) => <option key={segmentKey(item)} value={segmentKey(item)}>
          片段 {index + 1} · {timeLabel(item.start_ms)}—{timeLabel(item.end_ms)} ·
          {item.student_alias ?? "归属待核验"} · {item.teacher_text ?? item.upstream_text}
        </option>)}
      </select></label>
      {current && <span className={styles.sourceBadge}>{sourceNames[current.source_kind]}</span>}
    </div>
    <ClassroomAnalysis classroom={classroom} items={timeline} current={current} selected={selected}
      onSelect={select} onSaved={refresh} active={active} view={view}>
      <div className={styles.inspector}>
      {timeline.length === 0 && view !== "review" && <div className={styles.empty}>
        请先接收发言并完成核验，再进入教学支持或发布。
      </div>}
      {timeline.map((item) => <article key={segmentKey(item)} hidden={segmentKey(item) !== selected}>
        <div hidden={view !== "review"}>
          <UtteranceReview classroom={classroom} utterance={item} onSaved={refresh} showAudio={false} />
        </div>
        <div className={view === "publishing" ? styles.publishingGrid : undefined}>
          <EvidencePanel classroom={classroom} utterance={item} view={view} onLocateSource={() => locate(item)} />
          <div hidden={view !== "publishing"} className={styles.card}>
            <div className={styles.notice}>事实修正后请重新核验、生成并发布新版。
              人工编辑记录保留；已下载的离线副本不能远程收回。</div>
            <button onClick={() => locate(item)}>返回发言重新核验</button>
            <CorrectionPanel classroom={classroom} utterance={item} onSaved={refresh} />
          </div>
        </div>
        <details hidden={view !== "review"} className={styles.audit}><summary>所选原话与接收版本</summary>
          <p>上游原话：{item.upstream_text}</p><p>教师修订：{item.teacher_text ?? "未修订"}</p>
          <p>{phaseNames[item.phase]} · 会话 {item.session_id} · 片段 {item.segment_id}</p>
          <p>匿名声源 {item.source_ref ?? "未提供"} · 上游修订 {item.revision} · 应用版本 {item.version}</p>
        </details>
      </article>)}
      </div>
    </ClassroomAnalysis>
    <details className={styles.replay}><summary>模拟事件回放 · 开发诊断</summary>
      <p>这里只回放合成事件，不采集麦克风、不调用真实语音服务。原音频可另行授权归档。</p>
      <p>样例包含临时转写、定稿、重复事件、断流缺口、恢复、修订和结束；固定讨论平均分与四分之一。</p>
      <button disabled={busy || running} onClick={() => {
        setPlan(simulationEvents()); setIndex(0); setRunning(true); setError("");
        setNotice("开始新的模拟会话，既有会话不会被覆盖。");
      }}>开始新回放</button>
      <button disabled={!running} onClick={() => {
        setRunning(false); setNotice("回放已暂停；正在发送的步骤仍会完成。");
      }}>暂停</button>
      <button disabled={busy || running || index >= plan.length} onClick={() => setRunning(true)}>继续</button>
      <p>进度：{index}/{plan.length}。暂停只控制模拟事件发送，不代表上游服务暂停。</p>
    </details>
    <details className={styles.audit}><summary>已保存事件与接收缺口（{events.length} 条）</summary>
      <p>缺失区间只表示未收到完整数据，不代表学生沉默。</p>
      <ul>{events.map((item) => <li key={`${item.session_id}/${item.event_id}`}>
        会话 {item.session_id}；序号 {item.sequence}；
        {item.event_type === "status" || item.event_type === "end"
          ? item.status ? statusNames[item.status] : "结束事件"
          : item.event_type === "metadata" ? "语音处理元数据" : phaseNames[item.event_type]}；来源：{sourceNames[item.source_kind]}
        {item.gap_start_ms !== null && <>；缺失区间 {item.gap_start_ms}—{item.gap_end_ms} 毫秒</>}
      </li>)}</ul>
    </details>
  </section>;
}
