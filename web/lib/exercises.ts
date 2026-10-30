import { z } from "zod";
import { request } from "./api";
import { evidenceRecordSchema } from "./evidence";

export const exerciseSchema = z.object({
  level: z.enum(["concept", "explanation", "transfer"]),
  question: z.string().trim().min(1).max(2000), answer: z.string().trim().min(1).max(2000),
  explanation: z.string().trim().min(1).max(3000),
});
export const exercisesSchema = z.array(exerciseSchema).length(3).refine(
  (items) => new Set(items.map((item) => item.level)).size === 3, "三道练习须分别覆盖三个层次",
);
const supportDraftSchema = z.object({
  evidence: z.object({ draft: evidenceRecordSchema.shape.original, teacher_confirmed: z.literal(true) }),
  content: z.object({
    exercises: exercisesSchema, classroom_question: z.string(), next_lesson: z.string(), check_method: z.string(),
  }),
  model: z.string(), status: z.literal("pending_teacher_review"),
});
const generateSchema = z.object({
  evidence_id: z.string(), expected_evidence_revision: z.number().int().positive(), idempotency_key: z.string(),
});
const taskSchema = z.object({
  id: z.string(), classroom_id: z.string(), request: generateSchema, basis: evidenceRecordSchema,
  status: z.enum(["running", "succeeded", "failed", "stale"]), error: z.string().nullable(),
  discarded_draft: supportDraftSchema.nullable(),
});
export const exerciseRecordSchema = z.object({
  id: z.string(), task_id: z.string(), classroom_id: z.string(), evidence_id: z.string(),
  evidence_revision: z.number().int(), original: supportDraftSchema, exercises: exercisesSchema,
  revision: z.number().int().positive(), status: z.enum(["pending", "confirmed", "rejected", "stale"]),
  reviewed_by: z.string().nullable(), adopted: z.boolean(), adopted_by: z.string().nullable(),
});
const resultSchema = z.object({ task: taskSchema, exercise_set: exerciseRecordSchema.nullable() });
export type Exercise = z.infer<typeof exerciseSchema>;
export type ExerciseRecord = z.infer<typeof exerciseRecordSchema>;
export type ExerciseResult = z.infer<typeof resultSchema>;
export type GenerateExercises = z.infer<typeof generateSchema>;
export const levelNames: Record<Exercise["level"], string> = {
  concept: "概念巩固", explanation: "解释表达", transfer: "情境迁移",
};
const route = (classroom: string) => `/classrooms/${encodeURIComponent(classroom)}/exercises`;
export const exercisesApi = {
  list: (classroom: string) => request(route(classroom), z.array(resultSchema)),
  generate: (classroom: string, body: GenerateExercises) => request(
    `${route(classroom)}/generate`, resultSchema, "POST", JSON.stringify(body),
  ),
  review: (classroom: string, id: string, revision: number,
    action: "pending" | "confirmed" | "rejected", exercises: Exercise[]) => request(
    `${route(classroom)}/${encodeURIComponent(id)}/review`, exerciseRecordSchema, "PUT",
    JSON.stringify({ expected_revision: revision, action, exercises }),
  ),
  adopt: (classroom: string, id: string, revision: number, adopted: boolean) => request(
    `${route(classroom)}/${encodeURIComponent(id)}/adoption`, exerciseRecordSchema, "PUT",
    JSON.stringify({ expected_revision: revision, adopted }),
  ),
};
export function mergeExercises(previous: ExerciseResult | undefined, incoming: ExerciseResult): ExerciseResult {
  if (!previous) return incoming;
  const record = previous.exercise_set;
  const exercise_set = record && (!incoming.exercise_set || record.id === incoming.exercise_set.id
    && record.revision > incoming.exercise_set.revision) ? record : incoming.exercise_set;
  const task = previous.task.status === "stale"
    || incoming.task.status === "running" && previous.task.status !== "running" ? previous.task : incoming.task;
  return { task, exercise_set };
}
