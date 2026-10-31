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
