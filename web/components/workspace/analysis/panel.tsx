"use client";

import { useEffect, useState, type ReactNode } from "react";
import type { Classroom } from "../../../lib/types";
import type { Utterance } from "../../../lib/speech";
import { AudioPanel } from "../../audio-panel";
import { QuestionDiagram } from "../../diagrams/question";
import { Timeline } from "../timeline";
import { SourceDetails } from "../speech/source-details";
import { segmentKey, timeLabel } from "../types";
import type { WorkspaceView } from "../types";
import { confirmedQuestionEvidence } from "../evidence-source";
import { useQuestionEvidence } from "./use-question-evidence";
import styles from "./panel.module.css";

const tabs = [["overview", "课堂概览"], ["questions", "提问分析"], ["transcript", "课堂实录"]] as const;

export function ClassroomAnalysis({ classroom, items, current, selected, onSelect, onSaved, active, view,
  sourceFocusVersion = 0, children }: {
  classroom: Classroom; items: Utterance[]; current?: Utterance; selected: string;
  onSelect: (item: Utterance) => void; onSaved: () => Promise<void>; active: boolean;
  view: WorkspaceView; sourceFocusVersion?: number; children: ReactNode;
}) {
  const [tab, setTab] = useState<(typeof tabs)[number][0]>("questions");
  const [mobilePane, setMobilePane] = useState<"audio" | "analysis">("analysis");
  const [narrow, setNarrow] = useState(false);
  const sourceId = current ? `utterance-${current.session_id}-${current.segment_id}` : "";
  useEffect(() => {
    const query = window.matchMedia("(max-width: 1000px)");
    const update = () => setNarrow(query.matches);
    update(); query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (sourceFocusVersion > 0) { setTab("transcript"); setMobilePane("analysis"); }
  }, [sourceFocusVersion]);
  useEffect(() => {
    if (view !== "review" || tab !== "transcript") return;
    const frame = requestAnimationFrame(() => {
      const panel = document.getElementById("analysis-transcript");
      const source = document.getElementById(sourceId);
      if (!panel || !source) return;
      panel.scrollTo({ top: panel.scrollTop + source.getBoundingClientRect().top
        - panel.getBoundingClientRect().top - (panel.clientHeight - source.clientHeight) / 2 });
    });
    return () => cancelAnimationFrame(frame);
  }, [view, tab, selected, sourceFocusVersion, sourceId]);
  const evidence = useQuestionEvidence(classroom.id, active && view === "review" && tab === "questions");
  const question = classroom.questions.find((item) => item.id === current?.question_id) ?? classroom.questions[0];
  const sessionItems = current ? items.filter((item) => item.session_id === current.session_id) : [];
  const end = Math.max(1, ...sessionItems.map((item) => item.end_ms));
  const confirmed = items.filter((item) => item.text_review === "confirmed"
    && item.identity_review === "confirmed" && item.question_review === "confirmed");
  const rows = [
    { name: "教师发言", values: sessionItems.filter((item) => item.source_kind === "recorded_result"
      && item.source_ref === "teacher") },
    { name: "学生发言", values: sessionItems.filter((item) => item.identity_review === "confirmed"
      || item.source_kind === "recorded_result" && /^student-\d{2,4}$/.test(item.source_ref ?? "")) },
    { name: "身份待核验", values: sessionItems.filter((item) => item.identity_review !== "confirmed") },
    { name: "重叠发言", values: sessionItems.filter((item) => item.overlap) },
    { name: "内容待核验", values: sessionItems.filter((item) => item.text_review !== "confirmed") },
  ];
  return <div className={view === "review" ? styles.columns : styles.full} data-mobile-pane={mobilePane}>
    {view === "review" && <div className={styles.mobileTabs} role="group" aria-label="选择课堂面板">
      <button type="button" aria-pressed={mobilePane === "audio"} onClick={() => setMobilePane("audio")}>
        音频与标注</button>
      <button type="button" aria-pressed={mobilePane === "analysis"} onClick={() => setMobilePane("analysis")}>
        分析与核验</button>
    </div>}
    <div hidden={view !== "review"} className={styles.left}>
      <section className={styles.media} aria-label="课堂音频与题目材料">
        <div className={styles.slide}>
          <span className={styles.audioLabel}>课堂音频 · 题目示意</span>
          <h2>{classroom.title}</h2>
          {question && <><div className={styles.diagram}><QuestionDiagram question={question} /></div>
            <p>{question.text}</p></>}
          {!question && <p>尚未提供题目材料</p>}
        </div>
        <div className={styles.player}>
          {current ? <><p>{timeLabel(current.start_ms)}—{timeLabel(current.end_ms)} · 当前发言范围</p>
            <AudioPanel key={segmentKey(current)} classroomId={classroom.id} utterance={current}
              onSaved={onSaved} active={active && view === "review" && (!narrow || mobilePane === "audio")} />
            <SourceDetails utterance={current} />
          </> : <p>接收音频结果后，可在此回听原始音频与处理音轨。</p>}
        </div>
      </section>
      <section className={styles.markers} aria-label="课堂时间标注">
        <h2>课堂时间标注</h2><p>当前会话已接收片段 · 点击标注定位发言</p>
        {sessionItems.length === 0 ? <p>尚无时间标注；收到真实语音结果后更新。</p> : <>
          {rows.map((row) => <div className={styles.markerRow} key={row.name}><span>{row.name}</span>
            <div className={styles.track}>{row.values.map((item) => <button type="button" key={segmentKey(item)}
              title={`${timeLabel(item.start_ms)}—${timeLabel(item.end_ms)} ${item.upstream_text || "无文字"}`}
              aria-label={`${row.name} ${timeLabel(item.start_ms)}至${timeLabel(item.end_ms)}`}
              aria-pressed={selected === segmentKey(item)} onClick={() => {
                onSelect(item); setTab("transcript"); setMobilePane("analysis");
              }}
              style={{ left: `${item.start_ms / end * 100}%`,
                width: `${Math.max(0.7, (item.end_ms - item.start_ms) / end * 100)}%` }} />)}
            </div></div>)}
          <div className={styles.axis}><span>00:00</span>
            <span>{timeLabel(end / 2)}</span><span>{timeLabel(end)}</span></div>
          <p>声源尚未标记为教师或学生时，不推断其角色。此范围不代表整节课时长。</p>
        </>}
      </section>
    </div>
    <div className={styles.right}>
      <div hidden={view !== "review"} className={styles.analysisPane}>
        <div className={styles.tabs} role="tablist" aria-label="课堂分析内容">
          {tabs.map(([value, label]) => <button key={value} type="button" role="tab" id={`analysis-tab-${value}`}
            tabIndex={tab === value ? 0 : -1} aria-selected={tab === value} aria-controls={`analysis-${value}`}
            onKeyDown={(event) => {
              const currentIndex = tabs.findIndex(([key]) => key === tab);
              const nextIndex = event.key === "ArrowRight" ? (currentIndex + 1) % tabs.length
                : event.key === "ArrowLeft" ? (currentIndex + tabs.length - 1) % tabs.length
                  : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : -1;
              if (nextIndex < 0) return;
              event.preventDefault(); setTab(tabs[nextIndex][0]);
              document.getElementById(`analysis-tab-${tabs[nextIndex][0]}`)?.focus();
            }} onClick={() => setTab(value)}>{label}</button>)}
        </div>
        <section role="tabpanel" id="analysis-overview" aria-labelledby="analysis-tab-overview"
          hidden={tab !== "overview"}
          className={styles.content}>
          <h2>课堂概览</h2><p>{classroom.objective}</p>
          <div className={styles.stats}><p><strong>{items.length}</strong>已接收片段</p>
            <p><strong>{confirmed.length}</strong>三项已核验</p>
            <p><strong>{classroom.questions.length}</strong>已配置题目</p></div>
          <h3>材料来源</h3><p>{classroom.source}</p><h3>使用授权</h3><p>{classroom.authorization}</p>
          <p>统计依据当前已接收记录，不推断未采集的课堂活动。</p>
        </section>
        <section role="tabpanel" id="analysis-questions" aria-labelledby="analysis-tab-questions"
          hidden={tab !== "questions"}
          className={styles.content}>
          {evidence.error && <p role="status">{evidence.error} 当前不展示未能重新核实的解释。</p>}
          {classroom.questions.map((item) => {
            const related = items.filter((entry) => entry.question_id === item.id
              && entry.question_review === "confirmed");
            const explanations = confirmedQuestionEvidence(evidence.results, classroom, items, item.id);
            return <article className={styles.question} key={item.id}>
              <header><h2>{item.text}</h2><span>教师配置题目</span></header>
              <h3>课堂背景</h3><p>{classroom.objective}</p>
              <h3>教师参考答案</h3><p>{item.reference_answer}</p>
              <h3>分析</h3>
              {explanations.length === 0 ? <p>暂无与当前发言版本匹配且经教师确认的学习证据解释。</p>
                : explanations.map((record) => <section key={record.id}>
                  <blockquote>{record.content.quote}</blockquote>
                  <p>{record.content.interpretation}</p>
                  <p>核验限制：{record.content.limitation}</p>
                  <button type="button" onClick={() => {
                    const source = items.find((entry) => entry.session_id === record.basis.session_id
                      && entry.segment_id === record.basis.segment_id);
                    if (source) { onSelect(source); setTab("transcript"); }
                  }}>查看证据原发言 · 版本 {record.basis.utterance_version}</button>
                </section>)}
              <footer><span>{related.length} 条已核验题目关联</span>
                {related.map((entry) => <button type="button" key={segmentKey(entry)} onClick={() => {
                  onSelect(entry); setTab("transcript");
                }}>{timeLabel(entry.start_ms)} 查看发言</button>)}
              </footer>
              <p className={styles.pending}>在“AI教学反馈”中生成并核验解释后展示。不根据题目文字推断认知层级。</p>
            </article>;
          })}
        </section>
        <section role="tabpanel" id="analysis-transcript" aria-labelledby="analysis-tab-transcript"
          hidden={tab !== "transcript"} className={styles.content}>
          <Timeline classroom={classroom} items={items} selected={selected} onSelect={onSelect} onSaved={onSaved}
            active={active && view === "review" && tab === "transcript"} showPlayback={false} />
        </section>
      </div>
      {children}
    </div>
  </div>;
}
