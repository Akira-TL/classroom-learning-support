import { z } from "zod";
import { ApiError } from "../api";
import { inputSessionSchema } from "./types";
import type { InputFrame, InputSession } from "./types";

async function call<T>(path: string, schema: z.ZodType<T>, method = "GET", body?: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method, body, credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(15000),
      headers: body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new ApiError(0, "音频传输超时或网络不可用，接收情况未确认；不能声称已完成。");
  }
  let raw: unknown;
  try { raw = await response.json(); }
  catch { throw new ApiError(response.status, `音频接口返回非预期内容（HTTP ${response.status}）。`); }
  if (!response.ok) {
    const error = z.object({ detail: z.string() }).safeParse(raw);
    throw new ApiError(response.status,
      `${error.success ? error.data.detail : "音频接口拒绝请求"}（HTTP ${response.status}）`);
  }
  const parsed = schema.safeParse(raw);
  if (!parsed.success) throw new ApiError(response.status, "音频会话响应格式不符，未确认处理成功。");
  return parsed.data;
}
export const inputPath = (cid: string) => `/api/classrooms/${encodeURIComponent(cid)}/input-sessions`;
const path = (cid: string, sid: string) => `${inputPath(cid)}/${encodeURIComponent(sid)}`;
export const inputsApi = {
  list: (cid: string) => call(inputPath(cid), z.array(inputSessionSchema)),
  get: (cid: string, sid: string) => call(path(cid, sid), inputSessionSchema),
  create: (cid: string, input_mode: InputSession["input_mode"], sample_rate: number) => call(
    inputPath(cid), inputSessionSchema, "POST", JSON.stringify({
      input_mode, sample_rate, channels: 1, encoding: "pcm_s16le",
    }),
  ),
  frame: (cid: string, sid: string, frame: InputFrame) => call(
    `${path(cid, sid)}/frames`, inputSessionSchema, "POST", JSON.stringify(frame),
  ),
  state: (cid: string, sid: string, action: "pause" | "resume") => call(
    `${path(cid, sid)}/state`, inputSessionSchema, "PUT", JSON.stringify({ action }),
  ),
  finish: (cid: string, sid: string, interrupted: boolean) => call(
    `${path(cid, sid)}/finish`, inputSessionSchema, "POST", JSON.stringify({ interrupted }),
  ),
  recover: (cid: string, sid: string) => call(`${path(cid, sid)}/recover`, inputSessionSchema, "POST"),
  audio: (cid: string, sid: string) => `${path(cid, sid)}/audio`,
};
export function encodePcm(bytes: Uint8Array): string {
  let binary = "";
  for (let index = 0; index < bytes.length; index++) binary += String.fromCharCode(bytes[index]);
  return btoa(binary);
}
