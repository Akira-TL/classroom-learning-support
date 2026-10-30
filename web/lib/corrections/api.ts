import { z } from "zod";
import { request } from "../api";
import { reviewStateSchema, utteranceSchema } from "../speech";

const correctionSchema = z.object({
  session_id: z.string(), segment_id: z.string(),
  review: z.object({
    expected_version: z.number().int().positive(), teacher_text: z.string().nullable(),
    student_alias: z.string().nullable(), question_id: z.string().nullable(),
    text_review: reviewStateSchema, identity_review: reviewStateSchema, question_review: reviewStateSchema,
  }),
});
const applySchema = correctionSchema.extend({ idempotency_key: z.string() });
const impactSchema = z.object({
  evidence_ids: z.array(z.string()), exercise_ids: z.array(z.string()), plan_ids: z.array(z.string()),
  student_report_ids: z.array(z.string()), parent_report_ids: z.array(z.string()),
  counts: z.object({
    evidence: z.number().int().nonnegative(), exercises: z.number().int().nonnegative(),
    plans: z.number().int().nonnegative(), student_reports: z.number().int().nonnegative(),
    parent_reports: z.number().int().nonnegative(),
  }),
});
const assessmentSchema = z.object({ current: utteranceSchema, impact: impactSchema });
const resultSchema = z.object({
  id: z.string(), classroom_id: z.string(), request: applySchema, utterance: utteranceSchema, impact: impactSchema,
});
export type Correction = z.infer<typeof correctionSchema>;
export type CorrectionApply = z.infer<typeof applySchema>;
export type CorrectionAssessment = z.infer<typeof assessmentSchema>;
export const correctionsApi = {
  preview: (classroom: string, body: Correction) => request(
    `/classrooms/${encodeURIComponent(classroom)}/corrections/preview`,
    assessmentSchema, "POST", JSON.stringify(body),
  ),
  apply: (classroom: string, body: CorrectionApply) => request(
    `/classrooms/${encodeURIComponent(classroom)}/corrections`, resultSchema, "POST", JSON.stringify(body),
  ),
};
