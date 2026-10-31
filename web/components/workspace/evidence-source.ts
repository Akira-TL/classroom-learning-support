import type { EvidenceRecord, GenerationResult } from "../../lib/evidence";
import type { Utterance } from "../../lib/speech";
import type { Classroom } from "../../lib/types";

export function evidenceForSource(record: EvidenceRecord, classroom: Classroom, utterance: Utterance): EvidenceRecord {
  const context = record.basis.context;
  const question = classroom.questions.find((item) => item.id === context.question_id);
  const current = record.classroom_id === classroom.id
    && record.basis.session_id === utterance.session_id && record.basis.segment_id === utterance.segment_id
    && record.basis.utterance_version === utterance.version && context.student_alias === utterance.student_alias
    && context.question_id === utterance.question_id && context.objective === classroom.objective
    && question?.text === context.question && question.reference_answer === context.reference_answer
    && question.diagram_required === context.diagram_required
    && question.diagram_description === context.diagram_description;
  return current ? record : { ...record, status: "stale" };
}

export function preferredEvidenceTask(results: GenerationResult[], classroom: Classroom, utterance: Utterance): string {
  const current = results.filter((result) => result.evidence
    && evidenceForSource(result.evidence, classroom, utterance).status !== "stale");
  return (current.filter((result) => result.evidence?.status === "confirmed").at(-1)
    ?? current.filter((result) => result.evidence?.status === "pending").at(-1)
    ?? current.at(-1) ?? results.at(-1))?.task.id ?? "";
}

export function confirmedQuestionEvidence(
  results: GenerationResult[], classroom: Classroom, utterances: Utterance[], questionId: string,
): EvidenceRecord[] {
  return results.flatMap((result) => {
    const record = result.evidence;
    if (!record || result.task.status !== "succeeded" || record.basis.context.question_id !== questionId) return [];
    const utterance = utterances.find((item) => item.session_id === record.basis.session_id
      && item.segment_id === record.basis.segment_id);
    if (!utterance || !["final", "revision"].includes(utterance.phase)
      || ![utterance.text_review, utterance.identity_review, utterance.question_review]
        .every((value) => value === "confirmed")) return [];
    const current = evidenceForSource(record, classroom, utterance);
    return current.status === "confirmed" ? [current] : [];
  });
}
