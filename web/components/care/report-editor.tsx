"use client";

import { useState, type FormEvent } from "react";
import { careApi } from "../../lib/care/api";
import type { CareReport, Comparison } from "../../lib/care/types";
import styles from "./care.module.css";

const statusNames: Record<CareReport["status"], string> = {
  draft: "待教师确认草稿", published: "已发布", revoked: "已撤回", stale: "依据已变化",
};
export function CareReportEditor({ classroomId, comparison, reports, onSaved }: {
  classroomId: string; comparison: Comparison | null; reports: CareReport[]; onSaved: () => Promise<void>;
}) {
  const [teacher, setTeacher] = useState("");
  const [student, setStudent] = useState("");
  const [parent, setParent] = useState("");
  const [followup, setFollowup] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const basis = [...comparison?.baseline ?? [], ...comparison?.current ?? []]
    .map((item) => ({ observation_id: item.id, revision: item.revision }));
  async function draft(event: FormEvent) {
    event.preventDefault(); if (!comparison || busy || basis.length === 0) return;
    setBusy(true); setMessage("");
    try {
      await careApi.draft(classroomId, { comparison: comparison.periods, basis, teacher_text: teacher,
        student_text: student, parent_text: parent, followup });
      setMessage("跟进草稿已保存，尚未向学生或家长发布。"); await onSaved();
    } catch (failure) { setMessage(failure instanceof Error ? failure.message : "草稿保存失败。"); }
    finally { setBusy(false); }
  }
  async function action(report: CareReport, value: "publish" | "revoke") {
    if (busy || !confirmed) return; setBusy(true); setMessage("");
    try {
      await careApi.action(classroomId, report, value); await onSaved();
      setMessage(value === "publish" ? "已分别发布学生反馈和家长反馈。" : "已撤回关怀反馈。");
    } catch (failure) { setMessage(failure instanceof Error ? failure.message : "操作未确认成功。"); }
    finally { setBusy(false); }
  }
  return <section className={styles.card}><h2>教师跟进与反馈</h2>
    <p className={styles.muted}>基于可核查观察安排交流，不根据声音推断性格、健康或心理诊断。</p>
    {reports.map((report) => <article className={styles.observation} key={report.id}>
      <span className={styles.badge}>{statusNames[report.status]} · 版本 {report.revision}</span>
      <h3>教师记录</h3><p>{report.teacher_text}</p><h3>跟进安排</h3><p>{report.followup}</p>
      <details><summary>核对学生与家长将看到的内容</summary>
        <h3>学生反馈</h3><p>{report.student_text}</p><h3>家长反馈</h3><p>{report.parent_text}</p></details>
      {report.status === "draft" && <button type="button" disabled={busy || !confirmed}
        onClick={() => void action(report, "publish")}>确认并发布此草稿</button>}
      {report.status === "published" && <button type="button" disabled={busy || !confirmed}
        onClick={() => void action(report, "revoke")}>撤回此反馈</button>}
    </article>)}
    <label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
      我已核对观察依据、学生归属及发布内容</label>
    <details><summary>编写新的跟进草稿</summary><form onSubmit={(event) => void draft(event)}>
      <fieldset disabled={busy}><label>教师记录<textarea required maxLength={5000} value={teacher}
        onChange={(event) => setTeacher(event.target.value)} /></label>
      <label>给学生的反馈<textarea required maxLength={5000} value={student}
        onChange={(event) => setStudent(event.target.value)} /></label>
      <label>给家长的反馈<textarea required maxLength={5000} value={parent}
        onChange={(event) => setParent(event.target.value)} /></label>
      <label>后续跟进<textarea required maxLength={3000} value={followup}
        onChange={(event) => setFollowup(event.target.value)} /></label>
      <button type="submit" disabled={!comparison || basis.length === 0}>保存为待确认草稿</button>
      {basis.length === 0 && <p>当前比较范围尚无已确认观察，补齐事实后才能形成关怀反馈。</p>}
      </fieldset></form></details>
    {message && <p role="status">{message}</p>}
  </section>;
}
