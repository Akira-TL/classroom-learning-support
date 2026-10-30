"use client";

import { useEffect, useState } from "react";
import type { Classroom } from "../lib/types";
import type { Utterance } from "../lib/speech";
import { evidenceApi, mergeResult, taskNames } from "../lib/evidence";
import type { EvidenceRecord, GenerateEvidence, GenerationResult } from "../lib/evidence";
import { EvidenceReview } from "./evidence-review";
import { ExercisePanel } from "./exercises/panel";

export function EvidencePanel({ classroom, utterance }: { classroom: Classroom; utterance: Utterance }) {
  const [results, setResults] = useState<GenerationResult[]>([]);
  const [attempt, setAttempt] = useState<GenerateEvidence | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const verified = [utterance.text_review, utterance.identity_review, utterance.question_review]
    .every((state) => state === "confirmed") && ["final", "revision"].includes(utterance.phase);

  function accept(incoming: GenerationResult[]) {
    const matched = incoming.filter((result) => result.task.basis.session_id === utterance.session_id
      && result.task.basis.segment_id === utterance.segment_id);
    setResults((previous) => matched.map((result) => mergeResult(
      previous.find((item) => item.task.id === result.task.id), result,
    )));
    setAttempt((previous) => previous ?? matched.at(-1)?.task.request ?? null);
    setLoaded(true);
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    evidenceApi.list(classroom.id).then((incoming) => {
      if (active) accept(incoming);
    }).catch((failure: unknown) => {
      if (active) setError(failure instanceof Error ? failure.message : "学习证据读取失败。");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [classroom.id, classroom.revision, utterance.session_id, utterance.segment_id, utterance.version]);

  async function refresh() {
    setLoading(true); setError("");
    try { accept(await evidenceApi.list(classroom.id)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "刷新失败。"); }
    finally { setLoading(false); }
  }

  async function generate(newAttempt: boolean) {
    const request = !newAttempt && attempt ? attempt : {
      session_id: utterance.session_id, segment_id: utterance.segment_id,
      expected_version: utterance.version, idempotency_key: crypto.randomUUID(),
    };
    setAttempt(request); setBusy(true); setError(""); setNotice("");
    try {
      const incoming = await evidenceApi.generate(classroom.id, request);
      setResults((previous) => {
        const existing = previous.find((item) => item.task.id === incoming.task.id);
        const merged = mergeResult(existing, incoming);
        return existing ? previous.map((item) => item.task.id === incoming.task.id ? merged : item)
          : [...previous, merged];
      });
      setNotice(taskNames[incoming.task.status]);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "证据生成请求失败。");
    } finally { setBusy(false); }
  }

  function updateRecord(updated: EvidenceRecord) {
    setResults((previous) => previous.map((result) => result.evidence?.id === updated.id
      ? mergeResult(result, { ...result, evidence: updated }) : result));
  }

  return <section aria-label="学习证据分析">
    <h4>学习证据</h4>
    <p>点击生成才会调用 DeepSeek 云端；仅发送必要的匿名教学文本，输出仍需教师判断。</p>
    {!verified && <p>请先完成文字、身份和题目的分别核验；临时、撤回或无法判断的发言不能生成个人证据。</p>}
    {error && <p role="alert">{error} 未确认请求成功；可重试同一次请求，或明确重新生成。</p>}
    <p role="status" aria-live="polite">{busy ? "请求处理中，尚未确认生成成功…" : notice}</p>
    <button disabled={busy || loading || !loaded || !verified} onClick={() => void generate(false)}>
      {attempt ? "重试同一次生成请求" : "生成学习证据"}
    </button>
    {attempt && <button disabled={busy || loading || !loaded || !verified} onClick={() => void generate(true)}>
      重新生成（新请求）
    </button>}
    <button disabled={loading} onClick={() => void refresh()}>{loading ? "正在读取…" : "刷新证据与任务"}</button>
    {attempt && <p>当前请求依据发言版本 {attempt.expected_version}。
      {attempt.expected_version !== utterance.version && "发言已更新；重试旧请求不会改用新版本，需明确重新生成。"}</p>}
    {!loading && results.length === 0 && <p>本发言尚无生成任务。</p>}
    {results.map((result) => <article key={result.task.id}>
      <p>任务 {result.task.id}：{taskNames[result.task.status]}；
        依据发言版本 {result.task.basis.utterance_version}</p>
      {result.task.error && <p role="alert">{result.task.error}</p>}
      {result.task.discarded_draft && <details>
        <summary>已丢弃的过期返回，仅供核对，未采用为有效证据</summary>
        <blockquote>{result.task.discarded_draft.content.quote}</blockquote>
        <p>{result.task.discarded_draft.content.interpretation}</p>
      </details>}
      {result.evidence ? <>
        <EvidenceReview classroomId={classroom.id} record={result.evidence} onSaved={updateRecord} />
        <ExercisePanel classroomId={classroom.id} evidence={result.evidence} />
      </> : <p>此任务没有可供确认的证据记录。</p>}
    </article>)}
  </section>;
}
