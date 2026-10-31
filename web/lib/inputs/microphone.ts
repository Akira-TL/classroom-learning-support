import { z } from "zod";
import { encodePcm, inputsApi } from "./api";
import type { CaptureCallbacks, InputSession } from "./types";

const pcmSchema = z.object({ type: z.literal("pcm"), samples: z.instanceof(ArrayBuffer) });
const flushedSchema = z.object({ type: z.literal("flushed") });
const overflowSchema = z.object({ type: z.literal("overflow") });

export class MicrophoneCapture {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private processor: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private mute: GainNode | null = null;
  private session: InputSession | null = null;
  private queue: Uint8Array[] = [];
  private queuedSamples = 0;
  private inFlightSamples = 0;
  private pumping: Promise<void> | null = null;
  private stopping = false;
  private interrupted = false;
  private failureReason: string | null = null;
  private finishPromise: Promise<void> | null = null;
  private flushAck: (() => void) | null = null;
  constructor(private cid: string, private callbacks: CaptureCallbacks) {}

  async start(): Promise<void> {
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("当前浏览器或地址不支持麦克风，请使用安全上下文。");
      this.context = new AudioContext({ sampleRate: 16000 });
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
      if (this.stopping) { stream.getTracks().forEach((track) => track.stop()); return; }
      this.stream = stream;
      const rate = this.context.sampleRate;
      if (rate < 8000 || rate > 48000) throw new Error(`当前音频上下文采样率 ${rate}Hz 超出8—48kHz限制，不做隐式转码。`);
      await this.context.audioWorklet.addModule("/audio-worklet/processor.js");
      if (this.stopping) return;
      this.processor = new AudioWorkletNode(this.context, "classroom-capture", {
        channelCount: 1, channelCountMode: "explicit", numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
      });
      this.processor.port.onmessage = (event: MessageEvent<unknown>) => this.message(event.data);
      this.processor.onprocessorerror = () => this.fail("音频处理器失败，已停止采集；缺失不能视作静音。");
      this.session = await inputsApi.create(this.cid, "microphone", rate);
      if (this.stopping) {
        const result = await inputsApi.finish(this.cid, this.session.id, true);
        this.callbacks.session(result); return;
      }
      this.callbacks.session(this.session);
      this.source = this.context.createMediaStreamSource(stream);
      this.mute = this.context.createGain(); this.mute.gain.value = 0;
      this.source.connect(this.processor); this.processor.connect(this.mute);
      this.mute.connect(this.context.destination);
      stream.getAudioTracks().forEach((track) => track.addEventListener("ended", () => {
        if (!this.stopping) this.fail("麦克风设备已断开，采集不完整。");
      }));
      await this.context.resume();
      this.context.onstatechange = () => {
        if (!this.stopping && this.context?.state !== "running") this.fail("音频上下文被暂停或中断，已停止本次采集。");
      };
    } catch (failure) {
      if (!this.stopping) {
        const explanations: Record<string, string> = {
          NotAllowedError: "麦克风权限被拒绝，或当前安全策略不允许采集。",
          NotFoundError: "没有找到可用的麦克风设备。",
          NotReadableError: "麦克风无法读取，可能被其他应用占用或发生设备错误。",
          OverconstrainedError: "当前设备无法满足音频采集条件。",
          AbortError: "麦克风初始化已取消或被设备中断。",
        };
        this.failureReason = failure instanceof Error
          ? explanations[failure.name] ?? failure.message : "麦克风无法启动。";
        this.callbacks.error(this.failureReason);
      }
      await this.stop(true);
    }
  }
  private message(raw: unknown) {
    if (overflowSchema.safeParse(raw).success) {
      this.fail("音频处理器待确认队列已达2秒，已停止；缺失不能视为静音。"); return;
    }
    if (flushedSchema.safeParse(raw).success) { this.flushAck?.(); return; }
    const parsed = pcmSchema.safeParse(raw);
    if (!parsed.success) { this.fail("音频处理器消息格式不符，不能继续确认完整采集。"); return; }
    if (!this.session) return;
    const bytes = new Uint8Array(parsed.data.samples);
    if (!bytes.length || bytes.length % 2 || bytes.length > 65536) {
      this.fail("麦克风音频帧格式异常，已停止。"); return;
    }
    const samples = bytes.length / 2;
    if (this.queuedSamples + this.inFlightSamples + samples > this.session.sample_rate * 2) {
      this.fail("传输积压超过2秒，已停止采集并标记中断，不会无限堆积或隐瞒缺口。"); return;
    }
    this.queue.push(bytes); this.queuedSamples += samples;
    if (!this.pumping) this.pumping = this.pump().finally(() => { this.pumping = null; });
  }
  private async pump(): Promise<void> {
    try {
      while (this.queue.length && this.session) {
        const bytes = this.queue.shift();
        if (!bytes) break;
        this.inFlightSamples = bytes.length / 2; this.queuedSamples -= this.inFlightSamples;
        const prior = this.session;
        const next = await inputsApi.frame(this.cid, prior.id, {
          sequence: prior.expected_sequence, start_sample: prior.received_samples,
          frame_count: this.inFlightSamples, pcm_base64: encodePcm(bytes),
        });
        if (next.received_samples !== prior.received_samples + this.inFlightSamples) {
          throw new Error("音频接收游标不符，已停止采集。");
        }
        this.session = next; this.inFlightSamples = 0; this.callbacks.session(next);
        if (!this.stopping) this.processor?.port.postMessage("ack");
      }
    } catch (failure) {
      this.queue = []; this.queuedSamples = 0; this.inFlightSamples = 0;
      this.fail(failure instanceof Error ? failure.message : "麦克风传输失败。");
    }
  }
  private fail(message: string) {
    this.failureReason = message;
    this.callbacks.error(message);
    void this.stop(true);
  }
  stop(interrupted = false): Promise<void> {
    this.interrupted ||= interrupted;
    if (this.finishPromise) return this.finishPromise;
    this.stopping = true;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.finishPromise = this.finish(interrupted);
    return this.finishPromise;
  }
  private async finish(interrupted: boolean): Promise<void> {
    try {
      if (this.processor && !interrupted && this.context?.state === "running") {
        await new Promise<void>((resolve) => {
          const timer = setTimeout(() => { interrupted = true; this.flushAck = null; resolve(); }, 1000);
          this.flushAck = () => { clearTimeout(timer); this.flushAck = null; resolve(); };
          this.processor?.port.postMessage("stop");
        });
      }
      interrupted ||= this.interrupted;
      if (interrupted) { this.queue = []; this.queuedSamples = 0; }
      this.source?.disconnect(); this.processor?.disconnect(); this.processor?.port.close(); this.mute?.disconnect();
      if (this.context && this.context.state !== "closed") await this.context.close();
      await this.pumping;
      interrupted ||= this.interrupted;
      if (this.session) {
        const result = await inputsApi.finish(this.cid, this.session.id, interrupted);
        this.session = result; this.callbacks.session(result);
        if (interrupted) this.callbacks.error(this.failureReason ?? "麦克风采集已中断，未归档为完整音频；请检查会话状态。");
      }
    } catch (failure) {
      this.callbacks.error(failure instanceof Error ? failure.message : "麦克风结束状态未确认。");
    } finally { this.callbacks.stopped(); }
  }
}
