"use client";

import { useState } from "react";
import type { Classroom } from "../../lib/types";
import type { Utterance } from "../../lib/speech";
import type { EvidenceRecord } from "../../lib/evidence";
import { evidenceNames } from "../../lib/evidence";
import { EvidenceReview } from "../evidence-review";
import { ExercisePanel } from "../exercises/panel";
import { PlanPanel } from "../plans/panel";
import { PublishPanel } from "../reports/publish-panel";
import { evidenceForSource } from "./evidence-source";
import { timeLabel } from "./types";
import type { WorkspaceView } from "./types";
import styles from "./workspace.module.css";
import publishing from "./publishing.module.css";

const destinations = [["student", "学生反馈"], ["parent", "家长摘要"], ["teacher", "教师报告"]] as const;

export function EvidenceWorkspace({ classroom, utterance, record, view, onSaved, onLocateSource }: {
  classroom: Classroom; utterance: Utterance; record: EvidenceRecord; view: WorkspaceView;
  onSaved: (updated: EvidenceRecord) => void; onLocateSource?: () => void;
}) {
  const [destination, setDestination] = useState<(typeof destinations)[number][0]>("student");
  const evidence = evidenceForSource(record, classroom, utterance);
  const anchor = encodeURIComponent(`utterance-${record.basis.session_id}-${record.basis.segment_id}`);
  return <div className={view === "teaching" ? styles.evidenceGrid : styles.publishingContent}>
    <div hidden={view !== "publishing"} className={publishing.header}>
      <div className={publishing.tabs} role="group" aria-label="选择发布内容">
        {destinations.map(([value, label]) => <button key={value} type="button"
          aria-pressed={destination === value} onClick={() => setDestination(value)}>{label}</button>)}
      </div>
      <div className={publishing.source}>
        <span className={evidence.status === "confirmed" ? styles.good : styles.warning}>
          {evidenceNames[evidence.status]}</span>
        <span>关联学生：{evidence.basis.context.student_alias} · 证据版本 {record.revision}</span>
        <a href={`#${anchor}`} onClick={onLocateSource ? (event) => {
          event.preventDefault(); onLocateSource();
        } : undefined}>查看原发言</a>
      </div>
      {evidence.status !== "confirmed" && <p className={styles.notice}>
        当前依据尚未确认或已变化，不能发布。请返回原发言重新核验后发布新版；旧报告不会自动恢复。
      </p>}
    </div>
    <aside hidden={view !== "teaching"} className={`${styles.card} ${styles.evidenceBackground}`}>
      <span className={styles.eyebrow}>本次教学支持的依据</span><h2>证据背景</h2>
      <span className={evidence.status === "confirmed" ? styles.good : styles.warning}>
        {evidenceNames[evidence.status]}</span>
      <blockquote>{evidence.content.quote}</blockquote>
      <p className={styles.muted}>关联学生：{evidence.basis.context.student_alias}</p>
      <p className={styles.muted}>片段 {timeLabel(utterance.start_ms)}—{timeLabel(utterance.end_ms)}</p>
      <a href={`#${anchor}`} onClick={onLocateSource ? (event) => {
        event.preventDefault(); onLocateSource();
      } : undefined}>查看原发言与核验</a>
      <h3>证据说明</h3><p>{evidence.content.interpretation}</p>
      <h3>核验限制</h3><p>{evidence.content.limitation}</p>
      {evidence.status !== "confirmed" && <p className={styles.notice}>
        当前依据尚未确认或已变化。请返回原发言核对，再明确生成并发布新版；旧报告不会自动恢复。
      </p>}
      <details className={styles.audit}><summary>版本与跟进问题</summary>
        <p>证据版本 {record.revision} · 依据发言版本 {record.basis.utterance_version}</p>
        <p>{evidence.content.follow_up_question}</p>
      </details>
    </aside>
    <div hidden={view !== "review"}>
      <EvidenceReview classroomId={classroom.id} record={evidence} onSaved={onSaved} />
    </div>
    <div hidden={view !== "teaching" && !(view === "publishing" && destination === "student")}
      className={styles.supportCard}>
      <ExercisePanel classroomId={classroom.id} evidence={evidence}
        view={view === "publishing" ? "publishing" : "teaching"} />
    </div>
    <div hidden={view !== "teaching" && !(view === "publishing" && destination === "teacher")}
      className={`${styles.supportCard} ${styles.planColumn}`}>
      <PlanPanel classroomId={classroom.id} evidence={evidence}
        view={view === "publishing" ? "publishing" : "teaching"} />
    </div>
    <div hidden={view !== "publishing" || destination !== "parent"} className={styles.supportCard}>
      <PublishPanel classroomId={classroom.id} evidence={evidence} />
    </div>
  </div>;
}
