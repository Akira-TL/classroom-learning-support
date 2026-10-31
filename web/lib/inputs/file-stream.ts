import { encodePcm, inputsApi } from "./api";
import type { CaptureCallbacks, InputSession } from "./types";
import type { PcmWav } from "./wav";

export class FileStream {
  private session: InputSession | null = null;
  private cursor = 0;
  private paused = false;
  private stopping = false;
  private finished = false;
  private loop: Promise<void> | null = null;
  private wake: (() => void) | null = null;
  private origin = 0;
  private control: Promise<void> | null = null;
  constructor(private cid: string, private wav: PcmWav, private callbacks: CaptureCallbacks) {}

  async start(): Promise<void> {
    this.session = await inputsApi.create(this.cid, "file_stream", this.wav.sampleRate, this.wav.channels);
    this.callbacks.session(this.session);
    if (this.stopping) { await this.finish(true); return; }
    this.origin = performance.now();
    this.loop = this.run();
  }
  private async wait(milliseconds: number): Promise<void> {
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => { this.wake = null; resolve(); }, Math.max(0, milliseconds));
      this.wake = () => { clearTimeout(timer); this.wake = null; resolve(); };
    });
  }
  private async run(): Promise<void> {
    try {
      while (!this.stopping && !this.paused && this.cursor < this.wav.samples && this.session) {
        const count = Math.min(Math.round(this.wav.sampleRate / 4), this.wav.samples - this.cursor);
        await this.wait(this.origin + (this.cursor + count) / this.wav.sampleRate * 1000 - performance.now());
        if (this.stopping || this.paused) break;
        // 超期从实际发送时刻顺延，确认耗时不重复加入下一帧；慢网络后也不突发追赶。
        this.origin = Math.max(this.origin, performance.now() - (this.cursor + count) / this.wav.sampleRate * 1000);
        const next = await inputsApi.frame(this.cid, this.session.id, {
          sequence: this.session.expected_sequence, start_sample: this.cursor, frame_count: count,
          pcm_base64: encodePcm(this.wav.pcm.subarray(
            this.cursor * this.wav.channels * 2, (this.cursor + count) * this.wav.channels * 2,
          )),
        });
        if (next.received_samples !== this.cursor + count) throw new Error("服务端确认样本游标异常，已停止发送。");
        this.cursor += count; this.session = next; this.callbacks.session(next);
      }
      if (!this.stopping && this.cursor === this.wav.samples) await this.finish(false);
    } catch (failure) {
      this.stopping = true;
      this.callbacks.error(failure instanceof Error ? failure.message : "文件传输失败。");
      await this.finish(true);
    }
  }
  pause(): Promise<void> {
    this.paused = true; this.wake?.();
    const operation = this.pauseAfterFrame();
    this.control = operation.finally(() => { this.control = null; });
    return this.control;
  }
  private async pauseAfterFrame(): Promise<void> {
    await this.loop;
    if (!this.session || this.stopping || this.finished) return;
    this.session = await inputsApi.state(this.cid, this.session.id, "pause");
    this.callbacks.session(this.session);
  }
  resume(): Promise<void> {
    const operation = this.resumeAfterPause();
    this.control = operation.finally(() => { this.control = null; });
    return this.control;
  }
  private async resumeAfterPause(): Promise<void> {
    if (!this.session || this.stopping || this.finished || !this.paused) return;
    this.session = await inputsApi.state(this.cid, this.session.id, "resume");
    this.callbacks.session(this.session); this.paused = false;
    this.origin = performance.now() - this.cursor / this.wav.sampleRate * 1000;
    this.loop = this.run();
  }
  async stop(interrupted = false): Promise<void> {
    this.stopping = true; this.wake?.(); await this.loop;
    try { await this.control; } catch { interrupted = true; }
    await this.finish(interrupted || this.cursor < this.wav.samples);
  }
  private async finish(interrupted: boolean): Promise<void> {
    if (!this.session || this.finished) return;
    this.finished = true;
    try {
      this.session = await inputsApi.finish(this.cid, this.session.id, interrupted);
      this.callbacks.session(this.session);
    }
    catch (failure) { this.callbacks.error(failure instanceof Error ? failure.message : "结束状态未确认。"); }
    finally { this.callbacks.stopped(); }
  }
}
