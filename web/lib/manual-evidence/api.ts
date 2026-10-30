import { request } from "../api";
import { resultSchema } from "../evidence";
import type { EvidenceContent, GenerateEvidence } from "../evidence";

export interface ManualEvidenceRequest extends GenerateEvidence { content: EvidenceContent }
export const manualEvidenceApi = {
  save: (classroom: string, body: ManualEvidenceRequest) => request(
    `/classrooms/${encodeURIComponent(classroom)}/evidence/manual`, resultSchema, "POST", JSON.stringify(body),
  ),
};
