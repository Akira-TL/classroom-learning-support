"use client";

import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import type { Utterance } from "../lib/speech";
import styles from "./workspace/workspace.module.css";

const assetSchema = z.object({ id: z.string(), duration_ms: z.number(), source: z.literal("teacher_uploaded_audio") });
const errorSchema = z.object({ detail: z.string() });

export function AudioPanel({ classroomId, utterance, onSaved, active = true }: {
  classroomId: string; utterance: Utterance; onSaved: () => Promise<void>; active?: boolean;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const player = useRef<HTMLAudioElement>(null);
  useEffect(() => { if (!active) player.current?.pause(); }, [active]);
  const base = `/api/classrooms/${encodeURIComponent(classroomId)}/speech/`
    + encodeURIComponent(utterance.session_id);

  async function upload() {
    if (!file) { setMessage("请先选择对应会话的PCM WAV音频。"); return; }
    if (file.size > 20 * 1024 * 1024) { setMessage("音频不能超过20MB。"); return; }
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`${base}/audio`, {
        method: "POST", body: file, credentials: "same-origin", headers: { "Content-Type": "audio/wav" },
      });
      const raw: unknown = await response.json();
      if (!response.ok) {
        const error = errorSchema.safeParse(raw);
        throw new Error(error.success ? error.data.detail : `音频归档失败（HTTP ${response.status}）`);
      }
      const asset = assetSchema.parse(raw);
      setMessage(`已归档教师提供的音频，时长 ${asset.duration_ms} 毫秒；不代表语音识别服务已接通。`);
      await onSaved();
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : "音频归档未确认成功。");
    } finally { setBusy(false); }
  }

  return <div className={styles.audio}>
    {utterance.audio_available ? <>
      <p className={styles.muted}>已归档原音频 · 定位到 {utterance.start_ms}—{utterance.end_ms} 毫秒</p>
      <audio ref={player} controls preload="none" aria-label="发言原音频"
        src={`${base}/${encodeURIComponent(utterance.segment_id)}/audio`
          + `#t=${utterance.start_ms / 1000},${utterance.end_ms / 1000}`} />
    </> : <>
      <div className={styles.notice}>本片段没有可回听的原音频，或时间范围不匹配。</div>
      <details><summary>归档对应会话音频</summary>
      <p>可归档本会话的成人模拟音频；不产生新转写。</p>
      <p>音频起点须对应会话的0毫秒，上传前核对来源与时间基准。原音频归档后不能覆盖。</p>
      <label>本会话音频（PCM WAV，20MB以内）
        <input type="file" accept=".wav,audio/wav" disabled={busy}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
      </label>
      <button type="button" disabled={busy || !file} onClick={() => void upload()}>
        {busy ? "正在归档…" : "归档本会话音频"}
      </button>
      </details>
    </>}
    {message && <p role="status">{message}</p>}
  </div>;
}
