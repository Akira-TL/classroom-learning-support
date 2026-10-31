import { z } from "zod";
export const comparisonRequestSchema = z.object({ student_id: z.string(), baseline_start: z.string(),
  baseline_end: z.string(), current_start: z.string(), current_end: z.string() });
export type CompareRequest = z.infer<typeof comparisonRequestSchema>;

export const tagLabelSchema = z.enum(["cough", "pen_sound", "snoring", "inattention", "sleeping", "other"]);
export const tagSchema = z.object({ tag_id: z.string().min(1).max(100), label: tagLabelSchema,
  original_label: z.string().min(1).max(100), category: z.enum(["audible_event", "external_state"]),
  start_ms: z.number().int().nonnegative(), end_ms: z.number().int().positive(),
  count: z.number().int().min(0).max(10000), note: z.string().max(2000).default(""),
  original_value: z.union([z.number(), z.string()]).nullable().optional() }).strict().superRefine((tag, context) => {
  if (tag.end_ms <= tag.start_ms) context.addIssue({ code: "custom", message: "标签结束时间须晚于开始时间" });
  if (["inattention", "sleeping"].includes(tag.label) && tag.category !== "external_state") {
    context.addIssue({ code: "custom", message: "走神和睡觉须标记为外部状态来源" });
  }
});
export const tagImportSchema = z.object({ import_id: z.string().min(1).max(100),
  student_id: z.string().regex(/^student-[0-9]{2,4}$/), observed_on: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  session_id: z.string().min(1).max(100), source_name: z.string().min(1).max(300),
  source_version: z.string().min(1).max(100), source_description: z.string().min(1).max(2000),
  data_origin: z.enum(["provided_annotation", "demonstration"]), capture_conditions: z.string().min(1).max(1000),
  captured_duration_ms: z.number().int().positive().max(86400000).nullable().default(null),
  identity_confirmed: z.boolean().default(false), confirmed: z.boolean().default(false),
  tags: z.array(tagSchema).min(1).max(500),
  transcripts: z.array(z.object({ start_ms: z.number().int().nonnegative(), end_ms: z.number().int().positive(),
    text: z.string() }).strict()).default([]) }).strict();
export const tagBatchSchema = tagImportSchema.extend({ id: z.string(), classroom_id: z.string(),
  teacher_id: z.string(), revision: z.number() });
export const tagComparisonSchema = z.object({ periods: comparisonRequestSchema,
  baseline: z.array(tagBatchSchema), current: z.array(tagBatchSchema), notes: z.array(z.string()),
  summaries: z.array(z.object({ label: tagLabelSchema, baseline_count: z.number().nullable(),
    current_count: z.number().nullable(), count_difference: z.number().nullable(),
    baseline_duration_ms: z.number().nullable(), current_duration_ms: z.number().nullable(),
    baseline_per_hour: z.number().nullable(), current_per_hour: z.number().nullable(),
    rate_difference: z.number().nullable(), notes: z.array(z.string()) })) });
export type TagImport = z.infer<typeof tagImportSchema>;
export type TagBatch = z.infer<typeof tagBatchSchema>;
export type TagComparison = z.infer<typeof tagComparisonSchema>;
export type TagValue = z.infer<typeof tagSchema>;
export const tagNames: Record<TagValue["label"], string> = {
  cough: "咳嗽", pen_sound: "玩笔相关声音", snoring: "打呼噜声", inattention: "走神", sleeping: "睡觉", other: "其他标签",
};
export const perspectives = [["teacher", "教师"], ["head_teacher", "班主任"], ["student", "学生"],
  ["parent", "家长"], ["teaching_director", "教导主任"]] as const;
export const perspectiveSchema = z.enum(["teacher", "head_teacher", "student", "parent", "teaching_director"]);
export type Perspective = z.infer<typeof perspectiveSchema>;
export const explanationSchema = z.object({ id: z.string(), classroom_id: z.string(), student_id: z.string(),
  perspective: perspectiveSchema, source_fingerprint: z.string(), model: z.string(), status: z.literal("generated"),
  content: z.object({ change_explanation: z.string(), followup_questions: z.array(z.string()),
    summary: z.string(), followup: z.string() }), comparison: tagComparisonSchema });
export type AutoExplanation = z.infer<typeof explanationSchema>;
export const recipientExplanationSchema = explanationSchema.omit({ classroom_id: true, comparison: true })
  .extend({ perspective: z.enum(["student", "parent"]) });
export type RecipientExplanation = z.infer<typeof recipientExplanationSchema>;
