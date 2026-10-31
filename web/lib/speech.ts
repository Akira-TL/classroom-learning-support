import { z } from "zod";
import { request } from "./api";
import { nativeEventSchema } from "./speech/native";

export const reviewStateSchema = z.enum(["pending", "confirmed", "unable"]);
const sourceSchema = z.enum(["synthetic", "recorded_result", "upstream_live"]);
export const speechEventSchema = z.object({
  protocol_version: z.literal("app-draft-1"), session_id: z.string(), event_id: z.string(),
  sequence: z.number().int().nonnegative(),
  event_type: z.enum(["partial", "final", "revision", "withdraw", "status", "end", "metadata"]),
  source_kind: sourceSchema, segment_id: z.string().nullable(), revision: z.number().int().positive(),
  start_ms: z.number().nonnegative(), end_ms: z.number().nonnegative(), text: z.string().nullable(),
  source_ref: z.string().nullable(), overlap: z.boolean(),
  status: z.enum(["running", "paused", "disconnected", "ended"]).nullable(),
  gap_start_ms: z.number().nullable(), gap_end_ms: z.number().nullable(),
  native_event: nativeEventSchema.nullable().optional(),
});
export const utteranceSchema = z.object({
  session_id: z.string(), segment_id: z.string(), revision: z.number().int(), sequence: z.number().int(),
  phase: z.enum(["partial", "final", "revision", "withdraw"]), source_kind: sourceSchema,
  start_ms: z.number(), end_ms: z.number(), upstream_text: z.string(),
  source_ref: z.string().nullable(), overlap: z.boolean(), version: z.number().int(),
  teacher_text: z.string().nullable(), student_alias: z.string().nullable(), question_id: z.string().nullable(),
  text_review: reviewStateSchema, identity_review: reviewStateSchema, question_review: reviewStateSchema,
  reviewed_by: z.string().nullable(), audio_available: z.boolean(),
  native_event: nativeEventSchema.nullable().optional(),
});
export type SpeechEvent = z.infer<typeof speechEventSchema>;
export type Utterance = z.infer<typeof utteranceSchema>;
export type ReviewState = z.infer<typeof reviewStateSchema>;
export interface ReviewRequest {
  expected_version: number; teacher_text: string | null; student_alias: string | null;
  question_id: string | null; text_review: ReviewState; identity_review: ReviewState;
  question_review: ReviewState;
}
const route = (classroom: string) => `/classrooms/${encodeURIComponent(classroom)}/speech`;
export const speech = {
  events: (id: string) => request(`${route(id)}/events`, z.array(speechEventSchema)),
  timeline: (id: string) => request(`${route(id)}/timeline`, z.array(utteranceSchema)),
  receive: (id: string, event: SpeechEvent) => request(
    `${route(id)}/events`, z.object({ created: z.boolean() }), "POST", JSON.stringify(event),
  ),
  review: (classroom: string, utterance: Utterance, body: ReviewRequest) => request(
    `${route(classroom)}/${encodeURIComponent(utterance.session_id)}`
      + `/${encodeURIComponent(utterance.segment_id)}/review`,
    utteranceSchema, "PUT", JSON.stringify(body),
  ),
};
export const reviewNames: Record<ReviewState, string> = {
  pending: "待核验", confirmed: "已确认", unable: "无法判断",
};
export const sourceNames: Record<Utterance["source_kind"], string> = {
  synthetic: "模拟事件", recorded_result: "已记录结果", upstream_live: "真实上游",
};
export const phaseNames: Record<Utterance["phase"], string> = {
  partial: "临时转写", final: "上游定稿", revision: "上游修订", withdraw: "已撤回",
};
export const statusNames = {
  running: "接收中", paused: "已暂停", disconnected: "已断流", ended: "已结束",
} as const;

export function simulationEvents(): SpeechEvent[] {
  const session = crypto.randomUUID();
  const base: SpeechEvent = {
    protocol_version: "app-draft-1", session_id: session, event_id: "", sequence: 0,
    event_type: "status", source_kind: "synthetic", segment_id: null, revision: 1,
    start_ms: 0, end_ms: 0, text: null, source_ref: null, overlap: false,
    status: null, gap_start_ms: null, gap_end_ms: null,
  };
  function event(sequence: number, content: Partial<SpeechEvent>): SpeechEvent {
    return { ...base, sequence, event_id: crypto.randomUUID(), ...content };
  }
  const utterance = { segment_id: "simulated-segment-01", source_ref: "anonymous-source-01" };
  const final = event(2, {
    ...utterance, event_type: "final", start_ms: 0, end_ms: 3000,
    text: "分成了四块，所以每一块都是四分之一。",
  });
  return [
    event(0, { status: "running" }),
    event(1, { ...utterance, event_type: "partial", end_ms: 2000, text: "分成了四块，所以" }),
    final, final,
    event(3, { status: "disconnected", gap_start_ms: 3000, gap_end_ms: 5000 }),
    event(4, { status: "running" }),
    event(5, {
      ...utterance, event_type: "revision", revision: 2, end_ms: 3000,
      text: "分成了四块，所以我觉得每一块都是四分之一。",
    }),
    event(6, { event_type: "end", status: "ended" }),
  ];
}
