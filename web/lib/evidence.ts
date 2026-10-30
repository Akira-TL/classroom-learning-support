import { z } from "zod";
import { request } from "./api";

const contextSchema = z.object({
  question_id: z.string(), question_revision: z.number(), objective: z.string(), question: z.string(),
  reference_answer: z.string(), diagram_required: z.boolean(), diagram_description: z.string().nullable(),
  utterance_id: z.string(), utterance_revision: z.number(), student_alias: z.string(), utterance: z.string(),
  text_confirmed: z.literal(true), identity_confirmed: z.literal(true), question_confirmed: z.literal(true),
});
export const evidenceContentSchema = z.object({
  quote: z.string().min(1).max(6000), interpretation: z.string().trim().min(1).max(3000),
  limitation: z.string().trim().min(1).max(2000), follow_up_question: z.string().trim().min(1).max(1000),
});
const draftSchema = z.object({
  context: contextSchema, content: evidenceContentSchema, model: z.string(),
  status: z.literal("pending_teacher_review"),
});
const basisSchema = z.object({
  session_id: z.string(), segment_id: z.string(), utterance_version: z.number(),
  question_fingerprint: z.string(), context: contextSchema,
});
const generateSchema = z.object({
  session_id: z.string(), segment_id: z.string(), expected_version: z.number().int().positive(),
  idempotency_key: z.string(),
});
const taskSchema = z.object({
  id: z.string(), classroom_id: z.string(), request: generateSchema, basis: basisSchema,
  status: z.enum(["running", "succeeded", "failed", "stale"]), error: z.string().nullable(),
  discarded_draft: draftSchema.nullable(),
  origin: z.enum(["deepseek", "teacher_manual"]).default("deepseek"),
  manual_content: evidenceContentSchema.nullable().optional(),
});
export const evidenceRecordSchema = z.object({
  id: z.string(), task_id: z.string(), classroom_id: z.string(), basis: basisSchema, original: draftSchema,
  content: evidenceContentSchema, revision: z.number().int().positive(),
  status: z.enum(["pending", "confirmed", "rejected", "stale"]), reviewed_by: z.string().nullable(),
});
export const resultSchema = z.object({ task: taskSchema, evidence: evidenceRecordSchema.nullable() });
export type EvidenceContent = z.infer<typeof evidenceContentSchema>;
export type EvidenceRecord = z.infer<typeof evidenceRecordSchema>;
export type GenerationResult = z.infer<typeof resultSchema>;
export type GenerateEvidence = z.infer<typeof generateSchema>;
export type EvidenceAction = "confirmed" | "rejected";
const route = (classroom: string) => `/classrooms/${encodeURIComponent(classroom)}/evidence`;

export const evidenceApi = {
  list: (classroom: string) => request(route(classroom), z.array(resultSchema)),
  generate: (classroom: string, body: GenerateEvidence) => request(
    `${route(classroom)}/generate`, resultSchema, "POST", JSON.stringify(body),
  ),
  review: (classroom: string, record: EvidenceRecord, revision: number,
    action: EvidenceAction, content: EvidenceContent) => request(
    `${route(classroom)}/${encodeURIComponent(record.id)}/review`, evidenceRecordSchema, "PUT",
    JSON.stringify({ expected_revision: revision, action, content }),
  ),
};
export const taskNames: Record<GenerationResult["task"]["status"], string> = {
  running: "正在生成", succeeded: "生成成功，仍需教师核验", failed: "生成失败", stale: "依据已变化，结果过期",
};
export const evidenceNames: Record<EvidenceRecord["status"], string> = {
  pending: "待教师确认", confirmed: "教师已确认", rejected: "教师已驳回", stale: "依据已变化，证据过期",
};

export function mergeResult(previous: GenerationResult | undefined, incoming: GenerationResult): GenerationResult {
  if (!previous) return incoming;
  const evidence = previous.evidence && (!incoming.evidence
    || previous.evidence.id === incoming.evidence.id
      && previous.evidence.revision > incoming.evidence.revision) ? previous.evidence : incoming.evidence;
  const task = previous.task.status === "stale"
    || incoming.task.status === "running" && previous.task.status !== "running" ? previous.task : incoming.task;
  return { task, evidence };
}
