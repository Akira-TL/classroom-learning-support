import { z } from "zod";
import { exercisesSchema } from "../exercises";

export const reportSummarySchema = z.object({
  id: z.string(), classroom_id: z.string(), student_id: z.string(), revision: z.number().int(),
  published_at: z.string(), status: z.enum(["published", "revoked", "stale"]),
});
export const studentReportSchema = reportSummarySchema.extend({ feedback: z.string(), exercises: exercisesSchema });
export const previewSchema = z.object({ student_id: z.string(), feedback: z.string(), exercises: exercisesSchema });
export const feedbackSchema = z.object({
  id: z.string(), classroom_id: z.string(), report_id: z.string(), report_revision: z.number().int(),
  student_id: z.string(), kind: z.enum(["exercise_feedback", "correction"]), text: z.string(),
  revision: z.number().int(), status: z.enum(["open", "accepted", "rejected", "answered"]),
  response: z.string().nullable(), handled_by: z.string().nullable(),
});
export const sourceSchema = z.object({
  original_report_revision: z.number().int(), session_id: z.string(), segment_id: z.string(),
  current_utterance_version: z.number().int(), original_student_id: z.string(),
  current_student_alias: z.string().nullable(), current_question_id: z.string().nullable(),
});
export const publishSchema = z.object({
  exercise_set_id: z.string(), expected_exercise_revision: z.number().int().positive(),
  student_id: z.string(), feedback: z.string().trim().min(1).max(6000),
});
export type ReportSummary = z.infer<typeof reportSummarySchema>;
export type StudentReport = z.infer<typeof studentReportSchema>;
export type StudentFeedback = z.infer<typeof feedbackSchema>;
export type FeedbackSource = z.infer<typeof sourceSchema>;
export type StudentPublish = z.infer<typeof publishSchema>;
export type StudentPreview = z.infer<typeof previewSchema>;
export const reportNames: Record<ReportSummary["status"], string> = {
  published: "已发布", revoked: "已撤回", stale: "依据已变化，等待新版",
};
export const feedbackNames: Record<StudentFeedback["status"], string> = {
  open: "待处理", accepted: "已受理", rejected: "已驳回", answered: "已回复",
};
