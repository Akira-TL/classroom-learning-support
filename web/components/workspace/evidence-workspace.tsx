"use client";

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

export function EvidenceWorkspace({ classroom, utterance, record, view, onSaved, onLocateSource }: {
  classroom: Classroom; utterance: Utterance; record: EvidenceRecord; view: WorkspaceView;
  onSaved: (updated: EvidenceRecord) => void; onLocateSource?: () => void;
}) {
  const evidence = evidenceForSource(record, classroom, utterance);
  const anchor = encodeURIComponent(`utterance-${record.basis.session_id}-${record.basis.segment_id}`);
  return <div className={view === "teaching" ? styles.evidenceGrid : styles.publishingContent}>
    <aside hidden={view === "review"} className={`${styles.card} ${styles.evidenceBackground}`}>
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
    <div hidden={view === "review"} className={styles.supportCard}>
      <ExercisePanel classroomId={classroom.id} evidence={evidence}
        view={view === "publishing" ? "publishing" : "teaching"} />
    </div>
    <div hidden={view === "review"} className={`${styles.supportCard} ${styles.planColumn}`}>
      <PlanPanel classroomId={classroom.id} evidence={evidence}
        view={view === "publishing" ? "publishing" : "teaching"} />
    </div>
    <div hidden={view !== "publishing"} className={styles.supportCard}>
      <PublishPanel classroomId={classroom.id} evidence={evidence} />
    </div>
  </div>;
}
