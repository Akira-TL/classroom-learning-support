"use client";

import { useEffect, useState } from "react";
import { taskNames } from "../../lib/evidence";
import type { EvidenceRecord } from "../../lib/evidence";
import { exercisesApi, mergeExercises } from "../../lib/exercises";
import type { ExerciseRecord, ExerciseResult, GenerateExercises } from "../../lib/exercises";
import { ExerciseReview } from "./review";
import { StudentPublishPanel } from "../students/publish-panel";

export function ExercisePanel({ classroomId, evidence }: { classroomId: string; evidence: EvidenceRecord }) {
  const [results, setResults] = useState<ExerciseResult[]>([]);
  const [attempt, setAttempt] = useState<GenerateExercises | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function accept(incoming: ExerciseResult[]) {
    const matched = incoming.filter((item) => item.task.request.evidence_id === evidence.id);
    setResults((previous) => matched.map((item) => mergeExercises(
      previous.find((result) => result.task.id === item.task.id), item,
    )));
    setAttempt((previous) => previous ?? matched.at(-1)?.task.request ?? null);
    setLoaded(true);
  }

  useEffect(() => {
    let active = true; setLoading(true);
    exercisesApi.list(classroomId).then((incoming) => { if (active) accept(incoming); })
      .catch((failure: unknown) => {
        if (active) setError(failure instanceof Error ? failure.message : "练习任务读取失败。");
      }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [classroomId, evidence.id, evidence.revision, evidence.status]);

  async function refresh() {
    setLoading(true); setError("");
    try { accept(await exercisesApi.list(classroomId)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "练习读取失败。"); }
    finally { setLoading(false); }
  }

  async function generate(newAttempt: boolean) {
    const body = !newAttempt && attempt ? attempt : {
      evidence_id: evidence.id, expected_evidence_revision: evidence.revision, idempotency_key: crypto.randomUUID(),
    };
    setAttempt(body); setBusy(true); setError(""); setNotice("");
    try {
      const incoming = await exercisesApi.generate(classroomId, body);
      setResults((previous) => {
        const existing = previous.find((result) => result.task.id === incoming.task.id);
        const merged = mergeExercises(existing, incoming);
        return existing ? previous.map((item) => item.task.id === incoming.task.id ? merged : item)
          : [...previous, merged];
      });
      setNotice(taskNames[incoming.task.status]);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "练习生成请求失败。"); }
    finally { setBusy(false); }
  }

  function updateRecord(updated: ExerciseRecord) {
    setResults((previous) => previous.map((item) => item.exercise_set?.id === updated.id
      ? mergeExercises(item, { ...item, exercise_set: updated }) : item));
  }

  const disabled = busy || loading || !loaded || evidence.status !== "confirmed";
  return <section aria-label="分层练习生成">
    <h5>基于此证据的三层练习</h5>
    <p>只有明确点击才调用 DeepSeek。输出需教师逐题核验，当前不自动发布给学生。</p>
    {evidence.status !== "confirmed" && <p>请先确认有效学习证据；未确认、驳回或过期证据不能生成练习。</p>}
    {error && <p role="alert">{error} 可重试同一次请求；重新生成会新建任务。</p>}
    <p role="status" aria-live="polite">{busy ? "正在请求练习，尚未确认成功…" : notice}</p>
    <button disabled={disabled} onClick={() => void generate(false)}>
      {attempt ? "重试同一次练习请求" : "生成三层练习"}
    </button>
    {attempt && <button disabled={disabled} onClick={() => void generate(true)}>重新生成练习（新请求）</button>}
    <button disabled={loading} onClick={() => void refresh()}>{loading ? "正在读取…" : "刷新练习与任务"}</button>
    {attempt && <p>当前请求依据证据版本 {attempt.expected_evidence_revision}。
      {attempt.expected_evidence_revision !== evidence.revision && "证据已更新；需明确重新生成才使用新版本。"}</p>}
    {!loading && results.length === 0 && <p>此证据尚无练习任务。</p>}
    {results.map((result) => <article key={result.task.id}>
      <p>练习任务 {result.task.id}：{taskNames[result.task.status]}；
        依据证据版本 {result.task.basis.revision}</p>
      {result.task.error && <p role="alert">{result.task.error}</p>}
      {result.task.discarded_draft && <p>旧返回已丢弃，仅留审计记录，未作为有效练习采用。</p>}
      {result.exercise_set ? <>
        <ExerciseReview classroomId={classroomId} record={result.exercise_set} onSaved={updateRecord} />
        <StudentPublishPanel classroomId={classroomId} exercise={result.exercise_set} />
      </> : <p>此任务没有可供核验的练习。</p>}
    </article>)}
  </section>;
}
