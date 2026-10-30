export interface PcmWav { sampleRate: number; samples: number; pcm: Uint8Array; }
function tag(view: DataView, offset: number): string {
  return String.fromCharCode(...[0, 1, 2, 3].map((index) => view.getUint8(offset + index)));
}
export function parseWav(buffer: ArrayBuffer): PcmWav {
  const view = new DataView(buffer);
  if (view.byteLength < 44 || tag(view, 0) !== "RIFF" || tag(view, 8) !== "WAVE") {
    throw new Error("只接受有效的 RIFF/WAVE 文件，不会自动转码或改采样率。");
  }
  const end = view.getUint32(4, true) + 8;
  if (end !== view.byteLength) throw new Error("WAV 声明长度与实际文件不一致。");
  let rate = 0;
  let formatFound = false;
  let pcm: Uint8Array | null = null;
  let offset = 12;
  for (; offset + 8 <= end;) {
    const name = tag(view, offset);
    const size = view.getUint32(offset + 4, true);
    const data = offset + 8;
    if (data + size > end) throw new Error("WAV 数据块越界或不完整。");
    if (name === "fmt ") {
      if (formatFound || size < 16) throw new Error("WAV 格式块缺失或重复。");
      const encoding = view.getUint16(data, true);
      const channels = view.getUint16(data + 2, true);
      rate = view.getUint32(data + 4, true);
      if (encoding !== 1 || channels !== 1 || view.getUint16(data + 14, true) !== 16
        || view.getUint16(data + 12, true) !== 2 || view.getUint32(data + 8, true) !== rate * 2) {
        throw new Error("仅支持 PCM16 单声道 WAV；不接受浮点、压缩、多声道或格式字段不一致的文件。");
      }
      formatFound = true;
    } else if (name === "data") {
      if (pcm) throw new Error("不支持包含多个音频数据块的 WAV。");
      pcm = new Uint8Array(buffer, data, size);
    }
    offset = data + size + (size % 2);
    if (offset > end) throw new Error("WAV 数据块填充不完整。");
  }
  if (offset !== end) throw new Error("WAV 尾部存在不完整的数据块。");
  if (!formatFound || !pcm || pcm.length === 0 || pcm.length % 2 || rate < 8000 || rate > 48000) {
    throw new Error("需提供采样率 8—48kHz、非空且样本完整的 PCM16 单声道 WAV。");
  }
  if (pcm.length > 20 * 1024 * 1024 - 44 || pcm.length / 2 > rate * 600) {
    throw new Error("音频超过本机诊断限制：最多10分钟且原始数据小于20MiB。");
  }
  return { sampleRate: rate, samples: pcm.length / 2, pcm };
}
