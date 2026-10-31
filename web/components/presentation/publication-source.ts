import type { EvidenceRecord } from "../../lib/evidence";

type EvidenceSource = Pick<EvidenceRecord, "id" | "classroom_id" | "revision" | "status">;
interface RecordBasis {
  evidence_id: string; evidence_revision: number; classroom_id: string;
  status: "pending" | "confirmed" | "rejected" | "stale";
}
export interface PublicationRead { context: string; status: "loading" | "ready" | "error"; }
export function publicationContext(classroomId: string, evidence: EvidenceSource): string {
  return JSON.stringify([classroomId, evidence.classroom_id, evidence.id, evidence.revision, evidence.status]);
}
export function publicationReady(classroomId: string, evidence: EvidenceSource, read: PublicationRead): boolean {
  return evidence.classroom_id === classroomId && evidence.status === "confirmed"
    && read.context === publicationContext(classroomId, evidence) && read.status === "ready";
}
export function publicationRecord<T extends RecordBasis>(
  record: T, classroomId: string, evidence: EvidenceSource, read: PublicationRead,
  taskStatus: "running" | "succeeded" | "failed" | "stale",
): Omit<T, "status"> & Pick<RecordBasis, "status"> {
  const current = publicationReady(classroomId, evidence, read) && record.classroom_id === classroomId
    && record.evidence_id === evidence.id && record.evidence_revision === evidence.revision
    && taskStatus === "succeeded";
  return current ? record : { ...record, status: "stale" };
}
export function choosePublicationTask(previous: string, items: readonly { id: string; valid: boolean }[]): string {
  return items.some((item) => item.id === previous) ? previous
    : items.findLast((item) => item.valid)?.id ?? items.at(-1)?.id ?? "";
}
