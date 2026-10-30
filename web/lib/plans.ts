import { z } from "zod";
import { request } from "./api";
import { evidenceRecordSchema } from "./evidence";
import { exerciseRecordSchema } from "./exercises";

export const planContentSchema = z.object({
  target_student: z.string().regex(/^student-[0-9]{2,4}$/),
  question: z.string().trim().min(1).max(2000), preparation: z.string().trim().max(2000),
  alternative: z.string().trim().max(2000), keep_content: z.string().trim().max(3000),
  activity: z.string().trim().min(1).max(3000), check_method: z.string().trim().min(1).max(2000),
});
const generateSchema = z.object({
  evidence_id: z.string(), expected_evidence_revision: z.number().int().positive(), idempotency_key: z.string(),
});
const taskSchema = z.object({
  id: z.string(), classroom_id: z.string(), request: generateSchema, basis: evidenceRecordSchema,
  status: z.enum(["running", "succeeded", "failed", "stale"]), error: z.string().nullable(),
  discarded_draft: exerciseRecordSchema.shape.original.nullable(),
});
const recordSchema = z.object({
  id: z.string(), task_id: z.string(), classroom_id: z.string(), evidence_id: z.string(),
  evidence_revision: z.number().int(), original: exerciseRecordSchema.shape.original,
  content: planContentSchema, revision: z.number().int().positive(),
  status: z.enum(["pending", "confirmed", "rejected", "stale"]), reviewed_by: z.string().nullable(),
  adopted: z.boolean(), adopted_by: z.string().nullable(),
  observations: z.array(z.object({ text: z.string(), teacher: z.string(), revision: z.number().int() })),
});
const resultSchema = z.object({ task: taskSchema, plan: recordSchema.nullable() });
export type PlanContent = z.infer<typeof planContentSchema>;
export type PlanRecord = z.infer<typeof recordSchema>;
export type PlanResult = z.infer<typeof resultSchema>;
export type GeneratePlan = z.infer<typeof generateSchema>;
export function planComplete(content: PlanContent): boolean {
  return Boolean(content.preparation.trim() && content.alternative.trim() && content.keep_content.trim());
}
const route = (classroom: string) => `/classrooms/${encodeURIComponent(classroom)}/plans`;
export const plansApi = {
  list: (classroom: string) => request(route(classroom), z.array(resultSchema)),
  generate: (classroom: string, body: GeneratePlan) => request(
    `${route(classroom)}/generate`, resultSchema, "POST", JSON.stringify(body),
  ),
  review: (classroom: string, id: string, revision: number,
    action: "confirmed" | "rejected", content: PlanContent) => request(
    `${route(classroom)}/${encodeURIComponent(id)}/review`, recordSchema, "PUT",
    JSON.stringify({ expected_revision: revision, action, content }),
  ),
  adopt: (classroom: string, id: string, revision: number, adopted: boolean, observation: string | null) => request(
    `${route(classroom)}/${encodeURIComponent(id)}/adoption`, recordSchema, "PUT",
    JSON.stringify({ expected_revision: revision, adopted, observation }),
  ),
};
export function mergePlans(previous: PlanResult | undefined, incoming: PlanResult): PlanResult {
  if (!previous) return incoming;
  const record = previous.plan;
  const plan = record && (!incoming.plan || record.id === incoming.plan.id
    && record.revision > incoming.plan.revision) ? record : incoming.plan;
  const task = previous.task.status === "stale"
    || incoming.task.status === "running" && previous.task.status !== "running" ? previous.task : incoming.task;
  return { task, plan };
}
