import { z } from "zod";

export const reliabilitySchema = z.enum(["usable", "needs_review", "undetermined", "failed"]);
export const nativeSourceSchema = z.object({
  source_id: z.string(), kind: z.enum(["azimuth", "anon_speaker"]), value: z.union([z.number(), z.string()]),
  unit: z.enum(["deg", "label"]), reference: z.string(), valid_from_ms: z.number(), valid_to_ms: z.number(),
  reliability_state: reliabilitySchema, rebind_hint: z.boolean().default(false),
});
export const audioRefSchema = z.object({
  id: z.string(), kind: z.enum(["raw", "denoised", "separated"]), offset_ms: z.number().default(0),
  note: z.string().nullable().optional(),
});
export const nativeEventSchema = z.object({
  protocol_version: z.literal("speech.v0.1"), session_id: z.string(), event_id: z.string(), sequence: z.number(),
  event_type: z.string(), segment_id: z.string().nullable().optional(), revision: z.number().nullable().optional(),
  start_ms: z.number().nullable().optional(), end_ms: z.number().nullable().optional(),
  text: z.string().nullable().optional(), source_ref: z.array(z.string()).default([]),
  sources: z.array(nativeSourceSchema).default([]), audio_ref: z.array(audioRefSchema).default([]),
  overlap: z.object({ present: z.boolean(), with: z.array(z.string()).optional(),
    with_segments: z.array(z.string()).optional() }).nullable().optional(),
  reliability_state: reliabilitySchema.nullable().optional(), status: z.string().nullable().optional(),
  data_origin: z.enum(["live", "file_replay", "simulated"]),
  diagnostics: z.object({
    engine: z.string().optional(), audio_kind: z.string().optional(),
    math_guard: z.object({ review_reasons: z.array(z.string()).default([]), policy: z.string().optional() })
      .nullable().optional(),
  }).nullable().optional(),
});
export type NativeSpeechEvent = z.infer<typeof nativeEventSchema>;
export type AudioRef = z.infer<typeof audioRefSchema>;
export const reliabilityNames: Record<z.infer<typeof reliabilitySchema>, string> = {
  usable: "上游可用，仍需教师核验", needs_review: "需重点核验", undetermined: "无法判断", failed: "处理失败",
};
export const trackNames: Record<AudioRef["kind"], string> = {
  raw: "原始音频", denoised: "去噪音频", separated: "分离音轨",
};
