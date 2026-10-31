"use client";

import type { Classroom } from "../../lib/types";
import type { Utterance } from "../../lib/speech";
import { phaseNames, sourceNames } from "../../lib/speech";
import { AudioPanel } from "../audio-panel";
import { segmentKey, timeLabel } from "./types";
import styles from "./workspace.module.css";

export function Timeline({ classroom, items, selected, onSelect, onSaved, active = true }: {
  classroom: Classroom; items: Utterance[]; selected: string;
  onSelect: (item: Utterance) => void; onSaved: () => Promise<void>; active?: boolean;
}) {
  const current = items.find((item) => segmentKey(item) === selected);
  return <section className={`${styles.card} ${styles.timeline}`} aria-label="课堂语音时间线">
    <div className={styles.cardHeading}><div><span className={styles.eyebrow}>按接收会话与片段查看</span>
      <h2>课堂语音与转写</h2></div><span className={styles.count}>{items.length} 个片段</span></div>
    <div className={styles.playback}>
      <h3>{current ? `${timeLabel(current.start_ms)}—${timeLabel(current.end_ms)}` : "选择发言后回听"}</h3>
      <p className={styles.muted}>播放使用已归档原音频；时间范围来自上游记录，未生成示意波形。</p>
      {current && <><p className={styles.eyebrow}>所选片段 · 上游原话</p>
        <blockquote>{current.upstream_text}</blockquote>
        {current.teacher_text && <p>教师修订：{current.teacher_text}</p>}
      </>}
      {items.map((item) => <div key={segmentKey(item)} hidden={segmentKey(item) !== selected}>
        <AudioPanel classroomId={classroom.id} utterance={item} onSaved={onSaved}
          active={active && segmentKey(item) === selected} />
      </div>)}
    </div>
    <h3>学生发言</h3>
    {items.length === 0 && <div className={styles.empty}>
      <h3>尚无发言片段</h3><p>接收上游结果，或在下方展开模拟事件回放开始演示。</p>
    </div>}
    <ol className={styles.timelineList}>
      {items.map((item) => {
        const key = segmentKey(item);
        const confirmed = [item.text_review, item.identity_review, item.question_review]
          .every((state) => state === "confirmed");
        return <li key={key}>
          <article id={`utterance-${item.session_id}-${item.segment_id}`} className={styles.timelineArticle}>
            <button className={styles.timelineButton} aria-pressed={selected === key} onClick={() => onSelect(item)}>
              <span className={styles.rowMeta}><time>{timeLabel(item.start_ms)}—{timeLabel(item.end_ms)}</time>
                <span className={styles.sourceBadge}>{sourceNames[item.source_kind]}</span></span>
              <span className={styles.rowSpeaker}>{item.student_alias ?? "学生归属待核验"}
                <span className={confirmed ? styles.good : styles.warning}>{confirmed ? "三项已核验" : "待核验"}</span>
              </span>
              <span className={styles.transcript}>{item.teacher_text ?? item.upstream_text}</span>
              <span className={styles.rowMeta}>{phaseNames[item.phase]}
                {item.overlap && " · 存在重叠语音"} · 发言版本 {item.version}</span>
            </button>
          </article>
        </li>;
      })}
    </ol>
  </section>;
}
