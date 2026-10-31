"use client";

import { useEffect, useState } from "react";
import type { Classroom } from "../lib/types";
import type { Utterance } from "../lib/speech";
import { evidenceApi, evidenceNames, mergeResult, taskNames } from "../lib/evidence";
import type { EvidenceRecord, GenerateEvidence, GenerationResult } from "../lib/evidence";
import { ManualEvidencePanel } from "./manual-evidence/panel";
import { EvidenceWorkspace } from "./workspace/evidence-workspace";
import { evidenceForSource, preferredEvidenceTask } from "./workspace/evidence-source";
import type { WorkspaceView } from "./workspace/types";
import styles from "./workspace/workspace.module.css";

export function EvidencePanel({ classroom, utterance, view = "review", onLocateSource }: {
  classroom: Classroom; utterance: Utterance; view?: WorkspaceView; onLocateSource?: () => void;
}) {
  const [results, setResults] = useState<GenerationResult[]>([]);
  const [attempt, setAttempt] = useState<GenerateEvidence | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedTask, setSelectedTask] = useState("");
  const selected = results.some((result) => result.task.id === selectedTask)
    ? selectedTask : preferredEvidenceTask(results, classroom, utterance);
  const hasEvidence = results.some((result) => result.evidence !== null);
  const verified = [utterance.text_review, utterance.identity_review, utterance.question_review]
    .every((state) => state === "confirmed") && ["final", "revision"].includes(utterance.phase);

  function accept(incoming: GenerationResult[]) {
    const matched = incoming.filter((result) => result.task.basis.session_id === utterance.session_id
      && result.task.basis.segment_id === utterance.segment_id);
    setResults((previous) => matched.map((result) => mergeResult(
      previous.find((item) => item.task.id === result.task.id), result,
    )));
    setAttempt((previous) => previous
      ?? matched.filter((item) => item.task.origin === "deepseek").at(-1)?.task.request ?? null);
    setLoaded(true);
    return matched;
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

  async function refresh(selectNewest = false) {
    setLoading(true); setError("");
    try {
      const matched = accept(await evidenceApi.list(classroom.id));
      if (selectNewest) setSelectedTask(matched.at(-1)?.task.id ?? "");
    }
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
      setSelectedTask(incoming.task.id);
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

  return <section aria-label="学习证据分析" className={view === "review" ? styles.card : styles.evidencePanel}>
    <div hidden={view !== "review"}>
    {error && <p role="alert">{error} 未确认请求成功；可重试同一次请求，或明确重新生成。</p>}
    <p role="status" aria-live="polite">{busy ? "请求处理中，尚未确认生成成功…" : notice}</p>
    <details className={styles.creationControls} open={!hasEvidence}>
    <summary>{hasEvidence ? "建立或生成另一份学习证据" : "建立学习证据"}</summary>
    <p className={styles.muted}>明确点击才调用 DeepSeek；必要的匿名教学文本发送至云端，输出仍需核验。</p>
    {!verified && <p>请先完成文字、身份和题目的分别核验；临时、撤回或无法判断的发言不能生成个人证据。</p>}
    <button disabled={busy || loading || !loaded || !verified} onClick={() => void generate(false)}>
      {attempt ? "重试同一次生成请求" : "生成学习证据"}
    </button>
    {attempt && <button disabled={busy || loading || !loaded || !verified} onClick={() => void generate(true)}>
      重新生成（新请求）
    </button>}
    <button disabled={loading} onClick={() => void refresh()}>{loading ? "正在读取…" : "刷新证据与任务"}</button>
    {attempt && <p>当前请求依据发言版本 {attempt.expected_version}。
      {attempt.expected_version !== utterance.version && "发言已更新；重试旧请求不会改用新版本，需明确重新生成。"}</p>}
    <details><summary>不调用模型 · 教师人工录入</summary>
      <ManualEvidencePanel classroomId={classroom.id} utterance={utterance} onSaved={() => refresh(true)} />
    </details>
    </details>
    </div>
    {view !== "review" && <div className={styles.workspaceHeading}>
      <h3>{view === "teaching" ? "学习证据 → 教学支持" : "发布与接收预览"}</h3>
      <button disabled={loading} onClick={() => void refresh()}>{loading ? "正在核实…" : "核实证据状态"}</button>
    </div>}
    {view !== "review" && error && <p role="alert">{error} 当前读取未成功，请核对后继续。</p>}
    {!loading && results.length === 0 && <div className={styles.empty}>
      本发言尚无生成或人工录入任务。请先在核验工作台建立证据。
    </div>}
    {results.length > 0 && <details className={styles.historySelect}>
      <summary>证据与历史任务（{results.length} 条）</summary>
      <div className={styles.taskSelect}>
      <label>查看证据与历史任务<select value={selected} onChange={(event) => setSelectedTask(event.target.value)}>
        {results.map((result, index) => <option key={result.task.id} value={result.task.id}>
          记录 {index + 1} · {result.task.origin === "teacher_manual" ? "教师人工稿" : "模型初稿"} ·
          {result.evidence
            ? `${evidenceNames[evidenceForSource(result.evidence, classroom, utterance).status]}`
              + ` · 版本 ${result.evidence.revision}`
            : taskNames[result.task.status]}
        </option>)}
      </select></label>
    </div></details>}
    {results.map((result) => <article className={styles.evidenceTask} key={result.task.id}
      hidden={result.task.id !== selected}>
      {result.task.error && <p role="alert">{result.task.error}</p>}
      {result.task.discarded_draft && <details>
        <summary>已丢弃的过期返回，仅供核对，未采用为有效证据</summary>
        <blockquote>{result.task.discarded_draft.content.quote}</blockquote>
        <p>{result.task.discarded_draft.content.interpretation}</p>
      </details>}
      {result.evidence ? <EvidenceWorkspace classroom={classroom} utterance={utterance}
        record={result.evidence} view={view} onSaved={updateRecord} onLocateSource={onLocateSource} />
        : <p>此任务没有可供确认的证据记录。</p>}
      <details className={styles.audit}><summary>生成任务与依据记录</summary>
        <p>任务 {result.task.id}：{result.task.origin === "teacher_manual"
          ? result.task.status === "succeeded" ? "人工初稿已保存，仍需教师核验" : taskNames[result.task.status]
          : taskNames[result.task.status]}；依据发言版本 {result.task.basis.utterance_version}</p>
      </details>
    </article>)}
  </section>;
}
