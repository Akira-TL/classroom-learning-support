export {};
declare const sampleRate: number;
declare class AudioWorkletProcessor { readonly port: MessagePort; }
declare function registerProcessor(name: string, processor: typeof AudioWorkletProcessor): void;

class CaptureProcessor extends AudioWorkletProcessor {
  private size = Math.round(sampleRate / 4);
  private bytes = new ArrayBuffer(this.size * 2);
  private view = new DataView(this.bytes);
  private filled = 0;
  private stopped = false;
  private pendingFrames = 0;
  constructor() {
    super();
    this.port.onmessage = (event: MessageEvent<unknown>) => {
      if (event.data === "ack") this.pendingFrames = Math.max(0, this.pendingFrames - 1);
      if (event.data === "stop") {
        this.stopped = true; this.flush(); this.port.postMessage({ type: "flushed" });
      }
    };
  }
  private flush() {
    if (!this.filled) return;
    if (this.pendingFrames >= 8) {
      this.stopped = true; this.filled = 0; this.port.postMessage({ type: "overflow" }); return;
    }
    this.pendingFrames++;
    const samples = this.bytes.slice(0, this.filled * 2);
    this.port.postMessage({ type: "pcm", samples }, [samples]);
    this.bytes = new ArrayBuffer(this.size * 2); this.view = new DataView(this.bytes); this.filled = 0;
  }
  process(inputs: Float32Array[][]): boolean {
    if (this.stopped) return false;
    const channel = inputs[0]?.[0];
    if (channel) for (let index = 0; index < channel.length; index++) {
      const sample = Math.max(-1, Math.min(1, channel[index]));
      this.view.setInt16(this.filled * 2, Math.round(sample < 0 ? sample * 32768 : sample * 32767), true);
      if (++this.filled === this.size) {
        this.flush();
        if (this.stopped) return false;
      }
    }
    return true;
  }
}
registerProcessor("classroom-capture", CaptureProcessor);
