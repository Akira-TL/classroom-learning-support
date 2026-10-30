import { z } from "zod";
import { request } from "./api";

const previewInputSchema = z.object({
  evidence_id: z.string(), expected_evidence_revision: z.number().int(), student_id: z.string(),
  summary: z.string(), home_activity: z.string(),
});
const previewSchema = z.object({ content: previewInputSchema, parent_id: z.string(), notice: z.string() });
const reportSchema = z.object({
  id: z.string(), classroom_id: z.string(), student_id: z.string(), revision: z.number().int(),
  status: z.enum(["published", "revoked", "stale"]), published_at: z.string(),
  summary: z.string().nullable(), home_activity: z.string().nullable(),
  evidence_id: z.string(), evidence_revision: z.number().int(),
});
const questionSchema = z.object({
  id: z.string(), report_id: z.string(), classroom_id: z.string(), parent_id: z.string(), text: z.string(),
  status: z.enum(["open", "answered", "dismissed"]), response: z.string().nullable(), revision: z.number().int(),
});
export type PreviewInput = z.infer<typeof previewInputSchema>;
export type ReportPreview = z.infer<typeof previewSchema>;
export type ParentReport = z.infer<typeof reportSchema>;
export type ParentQuestion = z.infer<typeof questionSchema>;
export const reportStatus = { published: "已发布", revoked: "已撤回", stale: "依据已变化，等待新版" };
export const questionStatus = { open: "待教师处理", answered: "教师已回复", dismissed: "教师已说明不采纳" };
const classroomPath = (id: string) => `/classrooms/${encodeURIComponent(id)}/parent-reports`;
const reportPath = (id: string) => `/parent-reports/${encodeURIComponent(id)}`;

export const reportsApi = {
  mine: () => request("/parent-reports", z.array(reportSchema)),
  list: (cid: string) => request(classroomPath(cid), z.array(reportSchema)),
  preview: (cid: string, input: PreviewInput) => request(
    `${classroomPath(cid)}/preview`, previewSchema, "POST", JSON.stringify(input),
  ),
  publish: (cid: string, input: PreviewInput, key: string) => request(
    classroomPath(cid), reportSchema, "POST", JSON.stringify({ ...input, idempotency_key: key }),
  ),
  revoke: (cid: string, report: ParentReport) => request(
    `${classroomPath(cid)}/${encodeURIComponent(report.id)}/revoke`, reportSchema, "POST",
    JSON.stringify({ expected_revision: report.revision }),
  ),
  questions: (id: string) => request(`${reportPath(id)}/questions`, z.array(questionSchema)),
  ask: (id: string, text: string, key: string) => request(
    `${reportPath(id)}/questions`, questionSchema, "POST", JSON.stringify({ text, idempotency_key: key }),
  ),
  queue: (cid: string) => request(
    `/classrooms/${encodeURIComponent(cid)}/parent-report-questions`, z.array(questionSchema),
  ),
  resolve: (cid: string, id: string, revision: number, status: "answered" | "dismissed", response: string) => request(
    `/classrooms/${encodeURIComponent(cid)}/parent-report-questions/${encodeURIComponent(id)}`,
    questionSchema, "PUT", JSON.stringify({ expected_revision: revision, status, response }),
  ),
};
