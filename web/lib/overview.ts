import { z } from "zod";
import { request } from "./api";

const ratioSchema = z.object({
  numerator: z.number().int().nonnegative(), denominator: z.number().int().nonnegative(),
  ratio: z.number().min(0).max(1).nullable(),
});
const supportMetricsSchema = z.object({
  source: z.literal("model_generated"), generated_count: z.number().int().nonnegative(),
  confirmed_count: z.number().int().nonnegative(), adopted_count: z.number().int().nonnegative(),
  confirmation_rate: ratioSchema, adoption_rate: ratioSchema,
});

const summarySchema = z.object({
  snapshot_at: z.string().datetime({ offset: true }), time_scope: z.literal("current_retained_state"),
  time_range: z.string(), plan_metrics: supportMetricsSchema, exercise_metrics: supportMetricsSchema,
  manual_exercise_metrics: z.object({
    source: z.literal("teacher_manual_general"), recorded_count: z.number().int().nonnegative(),
    confirmed_count: z.number().int().nonnegative(), adopted_count: z.number().int().nonnegative(),
    confirmation_rate: ratioSchema, adoption_rate: ratioSchema,
  }),
  scope: z.string(), classroom_count: z.number().int().nonnegative(),
  adopted_plan_count: z.number().int().nonnegative(), adopted_exercise_count: z.number().int().nonnegative(),
  observation_count: z.number().int().nonnegative(),
  resource_needs: z.array(z.object({
    kind: z.enum(["exercise_materials", "teaching_activities", "manual_exercise_materials"]), description: z.string(),
    count: z.number().int().nonnegative(),
  })),
  performance_state: z.enum(["no_data", "hidden", "available"]),
  confirmed_evidence_count: z.number().int().nonnegative().nullable(),
  observed_student_count: z.number().int().nonnegative().nullable(),
  minimum_students: z.literal(5), hidden: z.boolean(), explanation: z.string(), counting_rule: z.string(),
});
export type AdminSummary = z.infer<typeof summarySchema>;
export type CountRatio = z.infer<typeof ratioSchema>;
export const getAdminSummary = () => request("/admin/summary", summarySchema);
