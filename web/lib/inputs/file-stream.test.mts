import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";
import type { TestContext } from "node:test";
import { z } from "zod";
import type { InputFrame, InputSession } from "./types.ts";

// 只为真实源码中的无扩展相对导入补上 .ts；不替换 FileStream 或其接口实现。
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith(".") && !/\.[a-z]+$/i.test(specifier)) {
      return nextResolve(`${specifier}.ts`, context);
    }
    return nextResolve(specifier, context);
  },
});
const { FileStream } = await import("./file-stream.ts");

interface Timer { at: number; callback: () => void; }
interface SentFrame extends InputFrame { at: number; }
const frameSchema = z.object({
  sequence: z.number().int(), start_sample: z.number().int(),
  frame_count: z.number().int(), pcm_base64: z.string(),
});
const stateSchema = z.object({ action: z.enum(["pause", "resume"]) });
const finishSchema = z.object({ interrupted: z.boolean() });
const createSchema = z.object({
  input_mode: z.literal("file_stream"), sample_rate: z.literal(16000),
  channels: z.literal(1), processing_mode: z.literal("speech_stream"), encoding: z.literal("pcm_s16le"),
});

class Clock {
  now = 0;
  private nextId = 0;
  private timers = new Map<number, Timer>();
  constructor(context: TestContext) {
    context.mock.method(performance, "now", () => this.now);
    context.mock.method(globalThis, "setTimeout", (callback: () => void, delay = 0) => {
      const id = ++this.nextId;
      this.timers.set(id, { at: this.now + Math.max(0, delay), callback });
      return id as unknown as ReturnType<typeof setTimeout>;
    });
    context.mock.method(globalThis, "clearTimeout", (id: ReturnType<typeof setTimeout>) => {
      this.timers.delete(id as unknown as number);
    });
  }
  async flush() { for (let index = 0; index < 40; index++) await Promise.resolve(); }
  async until(target: number) {
    await this.flush();
    while (true) {
      const next = [...this.timers.entries()].sort((a, b) => a[1].at - b[1].at)[0];
      if (!next || next[1].at > target) break;
      this.now = next[1].at;
      this.timers.delete(next[0]); next[1].callback();
      await this.flush();
    }
    this.now = target;
    await this.flush();
  }
}

function setup(context: TestContext, delays: readonly number[], samples = 16000) {
  const clock = new Clock(context);
  const frames: SentFrame[] = [];
  const errors: string[] = [];
  const finishes: boolean[] = [];
  let stopped = 0;
  let session: InputSession = {
    id: "input-test", classroom_id: "class-test", input_mode: "file_stream",
    processing_mode: "speech_stream", recognizer_connected: true, speech_session_id: "ses-test",
    forwarding_pending: false, speech_error: null, encoding: "pcm_s16le", sample_rate: 16000,
    channels: 1, status: "recording", received_samples: 0, expected_sequence: 0, audio_asset: null, error: null,
  };
  context.mock.method(globalThis, "fetch", async (input: Parameters<typeof fetch>[0], init?: RequestInit) => {
    assert.equal(typeof input, "string");
    assert.equal(typeof init?.body, "string");
    const body: unknown = JSON.parse(String(init?.body));
    if (String(input).endsWith("/frames")) {
      const frame = frameSchema.parse(body);
      assert.equal(frame.sequence, session.expected_sequence);
      assert.equal(frame.start_sample, session.received_samples);
      assert.equal(Buffer.from(frame.pcm_base64, "base64").length, frame.frame_count * 2);
      frames.push({ ...frame, at: clock.now });
      const delay = delays[frames.length - 1] ?? 120;
      await new Promise<void>((resolve) => setTimeout(resolve, delay));
      session = { ...session, received_samples: frame.start_sample + frame.frame_count,
        expected_sequence: frame.sequence + 1 };
    } else if (String(input).endsWith("/state")) {
      const { action } = stateSchema.parse(body);
      session = { ...session, status: action === "pause" ? "paused" : "recording" };
    } else if (String(input).endsWith("/finish")) {
      const { interrupted } = finishSchema.parse(body);
      finishes.push(interrupted);
      session = { ...session, status: interrupted ? "failed" : "ended" };
    } else {
      assert.equal(String(input), "/api/classrooms/class-test/input-sessions");
      createSchema.parse(body);
    }
    return new Response(JSON.stringify(session), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  const stream = new FileStream("class-test", {
    sampleRate: 16000, channels: 1, samples, pcm: new Uint8Array(samples * 2),
  }, {
    session: () => {}, error: (message) => errors.push(message), stopped: () => { stopped++; },
  });
  return { clock, stream, frames, errors, finishes, get stopped() { return stopped; } };
}

test("确认耗时小于帧长时，文件在250毫秒采样边界发送而不累计确认延迟", async (context) => {
  const env = setup(context, [120, 120, 120, 120]);
  await env.stream.start();
  await env.clock.until(1800);
  assert.deepEqual(env.frames.map((frame) => frame.at), [250, 500, 750, 1000]);
  assert.deepEqual(env.frames.map((frame) => frame.start_sample), [0, 4000, 8000, 12000]);
  assert.deepEqual(env.finishes, [false]);
  assert.deepEqual(env.errors, []);
  assert.equal(env.stopped, 1);
});

test("一次确认超过帧长后，恢复发送不以短于250毫秒的间隔追赶", async (context) => {
  const env = setup(context, [600, 0, 0, 0]);
  await env.stream.start();
  await env.clock.until(2500);
  assert.equal(env.frames.length, 4);
  for (let index = 1; index < env.frames.length; index++) {
    assert.ok(env.frames[index].at - env.frames[index - 1].at >= 250, "确认积压后发生突发追赶");
  }
  assert.deepEqual(env.finishes, [false]);
  assert.deepEqual(env.errors, []);
});

test("暂停等待在途确认，继续保留游标与帧序，停止取消下一帧并标记未播完", async (context) => {
  const env = setup(context, [120, 120], 16000);
  await env.stream.start();
  await env.clock.until(300);
  const pausing = env.stream.pause();
  await env.clock.until(900);
  await pausing;
  assert.deepEqual(env.frames.map((frame) => frame.sequence), [0]);
  await env.stream.resume();
  await env.clock.until(1270);
  assert.deepEqual(env.frames.map((frame) => [frame.at, frame.sequence, frame.start_sample]), [
    [250, 0, 0], [1150, 1, 4000],
  ]);
  await env.stream.stop();
  await env.clock.until(3000);
  assert.equal(env.frames.length, 2);
  assert.deepEqual(env.finishes, [true]);
  assert.equal(env.stopped, 1);
  assert.deepEqual(env.errors, []);
});
