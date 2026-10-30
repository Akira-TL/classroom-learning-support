import { z } from "zod";
import { request } from "../api";
import { feedbackSchema, previewSchema, reportSummarySchema, sourceSchema, studentReportSchema } from "./types";
import type { StudentFeedback, StudentPublish } from "./types";

const classUrl = (cid: string) => `/classrooms/${encodeURIComponent(cid)}`;
const reportUrl = (id: string) => `/student-reports/${encodeURIComponent(id)}`;
export const studentsApi = {
  list: () => request("/student-reports", z.array(reportSummarySchema)),
  read: (id: string) => request(reportUrl(id), studentReportSchema),
  feedback: (id: string) => request(`${reportUrl(id)}/feedback`, z.array(feedbackSchema)),
  submit: (id: string, kind: StudentFeedback["kind"], text: string, key: string) => request(
    `${reportUrl(id)}/feedback`, feedbackSchema, "POST", JSON.stringify({ kind, text, idempotency_key: key }),
  ),
  preview: (cid: string, body: StudentPublish) => request(
    `${classUrl(cid)}/student-reports/preview`, previewSchema, "POST", JSON.stringify(body),
  ),
  publish: (cid: string, body: StudentPublish, key: string) => request(
    `${classUrl(cid)}/student-reports`, studentReportSchema, "POST", JSON.stringify({ ...body, idempotency_key: key }),
  ),
  classReports: (cid: string) => request(`${classUrl(cid)}/student-reports`, z.array(reportSummarySchema)),
  revoke: (cid: string, id: string, revision: number) => request(
    `${classUrl(cid)}/student-reports/${encodeURIComponent(id)}/revoke`, reportSummarySchema, "POST",
    JSON.stringify({ expected_revision: revision }),
  ),
  queue: (cid: string) => request(`${classUrl(cid)}/student-feedback`, z.array(feedbackSchema)),
  source: (cid: string, id: string) => request(
    `${classUrl(cid)}/student-feedback/${encodeURIComponent(id)}/source`, sourceSchema,
  ),
  handle: (cid: string, id: string, revision: number,
    status: "accepted" | "rejected" | "answered", response: string) => request(
    `${classUrl(cid)}/student-feedback/${encodeURIComponent(id)}`, feedbackSchema, "PUT",
    JSON.stringify({ expected_revision: revision, status, response }),
  ),
};
