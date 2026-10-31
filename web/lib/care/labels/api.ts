import { request } from "../../api";
import type { CompareRequest } from "../types";
import { explanationSchema, recipientExplanationSchema, tagBatchSchema, tagComparisonSchema } from "./types";
import type { Perspective, TagImport } from "./types";

const route = (cid: string) => `/classrooms/${encodeURIComponent(cid)}/care`;
export const labelsApi = {
  import: (cid: string, body: TagImport) => request(`${route(cid)}/tag-batches`, tagBatchSchema,
    "POST", JSON.stringify(body)),
  compare: (body: CompareRequest) => request("/care/tag-comparison", tagComparisonSchema, "POST", JSON.stringify(body)),
  explain: (cid: string, comparison: CompareRequest, perspective: Perspective) => request(
    `${route(cid)}/explanations`, explanationSchema, "POST", JSON.stringify({ comparison, perspective })),
  mine: (comparison: CompareRequest, perspective: "student" | "parent") => request(
    "/care/me/explanations", recipientExplanationSchema, "POST", JSON.stringify({ comparison, perspective })),
};
