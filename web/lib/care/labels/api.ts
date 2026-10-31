import { request } from "../../api";
import type { CompareRequest } from "../types";
import { batchAudioAssetSchema, explanationSchema, recipientExplanationSchema,
  tagBatchSchema, tagComparisonSchema } from "./types";
import { z } from "zod";
import type { Perspective, TagImport } from "./types";

const route = (cid: string) => `/classrooms/${encodeURIComponent(cid)}/care`;
export const batchAudioPath = (cid: string, bid: string) =>
  `/api${route(cid)}/tag-batches/${encodeURIComponent(bid)}/audio`;
const audioErrorSchema = z.object({ detail: z.string() });
export const labelsApi = {
  import: (cid: string, body: TagImport) => request(`${route(cid)}/tag-batches`, tagBatchSchema,
    "POST", JSON.stringify(body)),
  compare: (body: CompareRequest) => request("/care/tag-comparison", tagComparisonSchema, "POST", JSON.stringify(body)),
  explain: (cid: string, comparison: CompareRequest, perspective: Perspective) => request(
    `${route(cid)}/explanations`, explanationSchema, "POST", JSON.stringify({ comparison, perspective })),
  mine: (comparison: CompareRequest, perspective: "student" | "parent") => request(
    "/care/me/explanations", recipientExplanationSchema, "POST", JSON.stringify({ comparison, perspective })),
  uploadAudio: async (cid: string, bid: string, file: File) => {
    const response = await fetch(batchAudioPath(cid, bid), { method: "POST", body: file,
      credentials: "same-origin", headers: { "Content-Type": "audio/wav" } });
    const payload: unknown = await response.json();
    if (!response.ok) {
      const error = audioErrorSchema.safeParse(payload);
      throw new Error(error.success ? error.data.detail : `音频上传失败（HTTP ${response.status}）`);
    }
    return batchAudioAssetSchema.parse(payload);
  },
};
