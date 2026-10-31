import { z } from "zod";
import { request } from "../api";
import { comparisonSchema, observationSchema, recipientSchema, reportSchema } from "./types";
import type { CareReport, CompareRequest, Observation, ObservationInput, ReportInput } from "./types";

const route = (cid: string) => `/classrooms/${encodeURIComponent(cid)}/care`;
export const careApi = {
  compare: (body: CompareRequest) => request("/care/compare", comparisonSchema, "POST", JSON.stringify(body)),
  observations: (cid: string) => request(`${route(cid)}/observations`, z.array(observationSchema)),
  confirmObservation: (item: Observation) => request(
    `${route(item.classroom_id)}/observations/${encodeURIComponent(item.id)}`, observationSchema, "PUT",
    JSON.stringify({ session_id: item.session_id, segment_id: item.segment_id,
      expected_utterance_version: item.expected_utterance_version, student_id: item.student_id,
      observed_on: item.observed_on, fact: item.fact, capture_conditions: item.capture_conditions,
      teacher_note: item.teacher_note, confirmed: true, expected_revision: item.revision })),
  observe: (cid: string, body: ObservationInput) => request(`${route(cid)}/observations`, observationSchema,
    "POST", JSON.stringify(body)),
  reports: (cid: string) => request(`${route(cid)}/reports`, z.array(reportSchema)),
  draft: (cid: string, body: ReportInput) => request(`${route(cid)}/reports`, reportSchema,
    "POST", JSON.stringify(body)),
  action: (cid: string, report: CareReport, action: "publish" | "revoke") => request(
    `${route(cid)}/reports/${encodeURIComponent(report.id)}/action`, reportSchema, "POST",
    JSON.stringify({ expected_revision: report.revision, action, teacher_confirmed: true })),
  mine: () => request("/care/me", z.array(recipientSchema)),
};
