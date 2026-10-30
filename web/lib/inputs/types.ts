import { z } from "zod";

export const inputSessionSchema = z.object({
  id: z.string(), classroom_id: z.string(), input_mode: z.enum(["microphone", "file_stream"]),
  processing_mode: z.literal("capture_only"), recognizer_connected: z.literal(false),
  encoding: z.literal("pcm_s16le"), sample_rate: z.number().int().min(8000).max(48000), channels: z.literal(1),
  status: z.enum(["recording", "paused", "finishing", "ended", "failed"]),
  received_samples: z.number().int().nonnegative(), expected_sequence: z.number().int().nonnegative(),
  audio_asset: z.object({
    id: z.string(), session_id: z.string(), duration_ms: z.number(), channels: z.number(),
    sample_rate: z.number(), source: z.string(),
  }).nullable(),
  error: z.string().nullable(),
});
export type InputSession = z.infer<typeof inputSessionSchema>;
export interface InputFrame { sequence: number; start_sample: number; frame_count: number; pcm_base64: string; }
export interface CaptureCallbacks {
  session: (value: InputSession) => void;
  error: (message: string) => void;
  stopped: () => void;
}
export interface CaptureController { stop: (interrupted?: boolean) => Promise<void>; }
export const inputStatusNames: Record<InputSession["status"], string> = {
  recording: "接收音频中", paused: "文件发送已暂停", finishing: "正在归档", ended: "音频归档完成", failed: "采集或传输中断",
};
