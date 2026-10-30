import { z } from "zod";
import { request } from "./api";

const summarySchema = z.object({
  scope: z.string(), classroom_count: z.number().int().nonnegative(),
  adopted_plan_count: z.number().int().nonnegative(), adopted_exercise_count: z.number().int().nonnegative(),
  observation_count: z.number().int().nonnegative(),
  resource_needs: z.array(z.object({
    kind: z.enum(["exercise_materials", "teaching_activities"]), description: z.string(),
    count: z.number().int().nonnegative(),
  })),
  performance_state: z.enum(["no_data", "hidden", "available"]),
  confirmed_evidence_count: z.number().int().nonnegative().nullable(),
  observed_student_count: z.number().int().nonnegative().nullable(),
  minimum_students: z.literal(5), hidden: z.boolean(), explanation: z.string(), counting_rule: z.string(),
});
export type AdminSummary = z.infer<typeof summarySchema>;
export const getAdminSummary = () => request("/admin/summary", summarySchema);
