import { z } from "zod";

export const comparisonRequestSchema = z.object({ student_id: z.string(), baseline_start: z.string(),
  baseline_end: z.string(), current_start: z.string(), current_end: z.string() });
export const observationInputSchema = z.object({ session_id: z.string(), segment_id: z.string(),
  expected_utterance_version: z.number(), student_id: z.string(), observed_on: z.string(), fact: z.string(),
  capture_conditions: z.string(), teacher_note: z.string(), confirmed: z.boolean() });
export const observationSchema = observationInputSchema.extend({ id: z.string(), classroom_id: z.string(),
  teacher_id: z.string(), revision: z.number(), source_current: z.boolean(), measurement_note: z.string(),
  measurements: z.object({ reliability: z.literal("verified"), method: z.string(), pitch_hz: z.number().nullable(),
    level_dbfs: z.number().nullable() }).nullable() });
export const comparisonSchema = z.object({ periods: comparisonRequestSchema,
  baseline: z.array(observationSchema), current: z.array(observationSchema), notes: z.array(z.string()),
  metrics: z.array(z.object({ name: z.enum(["pitch_hz", "level_dbfs"]), unit: z.enum(["Hz", "dBFS"]),
    baseline_count: z.number(), current_count: z.number(), baseline_mean: z.number().nullable(),
    current_mean: z.number().nullable(), difference: z.number().nullable(), comparable: z.boolean(),
    explanation: z.string() })) });
export const reportInputSchema = z.object({ comparison: comparisonRequestSchema,
  basis: z.array(z.object({ observation_id: z.string(), revision: z.number() })),
  teacher_text: z.string(), student_text: z.string(), parent_text: z.string(), followup: z.string() });
export const reportSchema = reportInputSchema.extend({ id: z.string(), classroom_id: z.string(),
  teacher_id: z.string(), student_id: z.string(), revision: z.number(),
  status: z.enum(["draft", "published", "revoked", "stale"]) });
export const recipientSchema = z.object({ id: z.string(), revision: z.number(), student_id: z.string(),
  audience: z.enum(["student", "parent"]), text: z.string(), status: z.literal("published") });
export type Observation = z.infer<typeof observationSchema>;
export type ObservationInput = z.infer<typeof observationInputSchema>;
export type CompareRequest = z.infer<typeof comparisonRequestSchema>;
export type Comparison = z.infer<typeof comparisonSchema>;
export type ReportInput = z.infer<typeof reportInputSchema>;
export type CareReport = z.infer<typeof reportSchema>;
export type RecipientReport = z.infer<typeof recipientSchema>;
