"use client";

import { useState } from "react";
import { manualEvidenceApi } from "../../lib/manual-evidence/api";
import type { ManualEvidenceRequest } from "../../lib/manual-evidence/api";
import { evidenceContentSchema } from "../../lib/evidence";
import type { Utterance } from "../../lib/speech";

export function ManualEvidencePanel({ classroomId, utterance, onSaved }: {
  classroomId: string; utterance: Utterance; onSaved: () => Promise<void>;
}) {
  const [basis, setBasis] = useState({
    classroom: classroomId, session: utterance.session_id, segment: utterance.segment_id,
    version: utterance.version, quote: utterance.teacher_text ?? utterance.upstream_text,
  });
  const [interpretation, setInterpretation] = useState("");
  const [limitation, setLimitation] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [attempt, setAttempt] = useState<ManualEvidenceRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const verified = [utterance.text_review, utterance.identity_review, utterance.question_review]
    .every((value) => value === "confirmed") && ["final", "revision"].includes(utterance.phase);
  const stale = basis.classroom !== classroomId || basis.session !== utterance.session_id
    || basis.segment !== utterance.segment_id || basis.version !== utterance.version;

  function edit(value: string, field: "interpretation" | "limitation" | "followUp") {
    if (field === "interpretation") setInterpretation(value);
    else if (field === "limitation") setLimitation(value);
    else setFollowUp(value);
    setAttempt(null); setNotice("");
  }

  async function save() {
    const content = evidenceContentSchema.safeParse({
      quote: basis.quote, interpretation, limitation, follow_up_question: followUp,
    });
    if (!content.success) {
      setError(content.error.issues.map((issue) => `${issue.path.join(".")}：${issue.message}`).join("；"));
      return;
    }
    const body = attempt ?? {
      session_id: basis.session, segment_id: basis.segment, expected_version: basis.version,
      idempotency_key: crypto.randomUUID(), content: content.data,
    };
    setAttempt(body); setBusy(true); setError(""); setNotice("");
    try {
      const result = await manualEvidenceApi.save(classroomId, body);
      setNotice(result.evidence?.status === "stale"
        ? "此请求对应的原稿已过期，编辑保留；请重新核验依据后另存新稿。"
        : "教师人工初稿已保存，仍需在证据记录中明确确认或驳回。未调用云端模型。");
      try { await onSaved(); }
      catch { setError("人工稿已保存，但列表刷新失败，请手动刷新学习证据。"); }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "保存未确认成功，可重试同一次请求。");
    } finally { setBusy(false); }
  }

  return <section aria-label="教师人工录入学习证据">
    <h4>教师人工录入学习证据</h4>
    <p>由教师填写解释、局限和跟进问题；本操作不调用 DeepSeek，保存后仍需独立确认。</p>
    {!verified && <p>须先分别核验发言文字、身份与题目；临时、撤回或无法判断的发言不能录入个人证据。</p>}
    {stale && <p role="alert">发言或来源已有变化，编辑保留。核对并载入最新原话后再保存。</p>}
    {error && <p role="alert">{error} 版本冲突不会自动覆盖，缺少图形时请先补充题目。</p>}
    <p role="status">{notice}</p>
    <blockquote>只读原话（依据发言版本 {basis.version}）：{basis.quote}</blockquote>
    <fieldset disabled={busy}>
      <legend>教师人工初稿</legend>
      <label>对本次回答的解释<textarea maxLength={3000} value={interpretation}
        onChange={(event) => edit(event.target.value, "interpretation")} /></label>
      <label>证据局限<textarea maxLength={2000} value={limitation}
        onChange={(event) => edit(event.target.value, "limitation")} /></label>
      <label>跟进问题<textarea maxLength={1000} value={followUp}
        onChange={(event) => edit(event.target.value, "followUp")} /></label>
      <button type="button" disabled={!verified || stale} onClick={() => void save()}>
        {attempt ? "重试同一次人工保存请求" : "保存教师人工初稿"}
      </button>
      <button type="button" onClick={() => {
        setBasis({ classroom: classroomId, session: utterance.session_id, segment: utterance.segment_id,
          version: utterance.version, quote: utterance.teacher_text ?? utterance.upstream_text });
        setAttempt(null); setError(""); setNotice("已载入当前原话，解释编辑保留；保存将使用新请求。");
      }}>载入页面最新原话并保留编辑</button>
    </fieldset>
  </section>;
}
