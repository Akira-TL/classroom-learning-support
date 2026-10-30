"use client";

import { useEffect, useRef, useState } from "react";
import type { ExerciseRecord } from "../../lib/exercises";
import { studentsApi } from "../../lib/students/api";
import { publishSchema, reportNames } from "../../lib/students/types";
import type { ReportSummary, StudentPreview } from "../../lib/students/types";

export function StudentPublishPanel({ classroomId, exercise }: { classroomId: string; exercise: ExerciseRecord }) {
  const [feedback, setFeedback] = useState("");
  const [preview, setPreview] = useState<StudentPreview | null>(null);
  const [previewSignature, setPreviewSignature] = useState("");
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const pending = useRef({ signature: "", key: "" });
  const student = exercise.original.evidence.draft.context.student_alias;
  const body = {
    exercise_set_id: exercise.id, expected_exercise_revision: exercise.revision, student_id: student, feedback,
  };
  const signature = JSON.stringify(body);
  const allowed = exercise.status === "confirmed" && Boolean(feedback.trim());

  useEffect(() => {
    let active = true;
    studentsApi.classReports(classroomId).then((items) => { if (active) setReports(items); })
      .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : "报告列表加载失败"); });
    return () => { active = false; };
  }, [classroomId]);

  async function showPreview() {
    setBusy(true); setError(""); setMessage("");
    try {
      const parsed = publishSchema.parse(body);
      const result = await studentsApi.preview(classroomId, parsed);
      setPreview(result); setPreviewSignature(signature);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "预览失败");
    } finally { setBusy(false); }
  }

  async function publish() {
    if (!preview || previewSignature !== signature) return;
    setBusy(true); setError(""); setMessage("");
    if (pending.current.signature !== signature) pending.current = { signature, key: crypto.randomUUID() };
    try {
      const result = await studentsApi.publish(classroomId, publishSchema.parse(body), pending.current.key);
      setReports((items) => [result, ...items.filter((item) => item.id !== result.id)]);
      setMessage(`已向 ${result.student_id} 发布报告，版本 ${result.revision}。`);
      setPreview(null);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "发布失败，原反馈已保留");
    } finally { setBusy(false); }
  }

  async function revoke(report: ReportSummary) {
    setBusy(true); setError("");
    try {
      const result = await studentsApi.revoke(classroomId, report.id, report.revision);
      setReports((items) => items.map((item) => item.id === result.id ? result : item));
      setMessage("报告已撤回，学生站内旧地址不再提供正文。");
    } catch (cause: unknown) { setError(cause instanceof Error ? cause.message : "撤回失败"); }
    finally { setBusy(false); }
  }

  return <section aria-label="向学生发布反馈">
    <h4>学生反馈与练习发布</h4>
    <p>对象：{student}。仅发布教师核验的反馈和练习，不含原音频及内部证据备注。</p>
    {exercise.status !== "confirmed" && <p>练习尚未确认或已失效，不能发布。</p>}
    <label>教师给学生的反馈<textarea maxLength={6000} value={feedback} onChange={(event) => {
      setFeedback(event.target.value); setPreview(null);
    }} /></label>
    <button disabled={busy || !allowed} onClick={() => void showPreview()}>预览接收内容</button>
    {preview && previewSignature === signature && <section aria-label="学生报告预览">
      <p>{preview.feedback}</p>
      {preview.exercises.map((item) => <div key={item.level}><p>{item.question}</p>
        <p>答案：{item.answer}；解释：{item.explanation}</p></div>)}
      <button disabled={busy || !allowed} onClick={() => void publish()}>确认向该学生发布</button>
    </section>}
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {reports.filter((item) => item.student_id === student).map((item) => <p key={item.id}>
      学生报告 {item.id.slice(0, 8)} · 版本 {item.revision} · {reportNames[item.status]}{" "}
      {item.status === "published" && <button disabled={busy} onClick={() => void revoke(item)}>撤回</button>}
    </p>)}
  </section>;
}
