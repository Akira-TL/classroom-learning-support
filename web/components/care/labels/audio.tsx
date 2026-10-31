"use client";

import { useEffect, useRef, useState } from "react";
import { batchAudioPath, labelsApi } from "../../../lib/care/labels/api";
import type { TagBatch } from "../../../lib/care/labels/types";
import { trackWindow } from "../../workspace/speech/track-time";
import { timeLabel } from "../../workspace/types";
import styles from "./labels.module.css";

export function BatchAudio({ batch, startMs, endMs, active, onSaved }: {
  batch: TagBatch; startMs: number; endMs: number; active: boolean; onSaved: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [asset, setAsset] = useState(batch.audio_asset);
  const player = useRef<HTMLAudioElement>(null);
  useEffect(() => { setAsset(batch.audio_asset); }, [batch.audio_asset]);
  useEffect(() => { if (!active) player.current?.pause(); }, [active]);
  useEffect(() => {
    const audio = player.current;
    if (audio && Number.isFinite(audio.duration)) {
      audio.pause();
      const bounds = trackWindow(startMs, endMs, 0, audio.duration);
      if (bounds.available) { audio.currentTime = bounds.start; setMessage(""); }
      else setMessage("原声未覆盖当前时间，不能回听此范围。");
    }
  }, [startMs, endMs]);
  async function upload() {
    if (!file || busy) return;
    if (file.size > 20 * 1024 * 1024) { setMessage("原始WAV音频不能超过20MB。"); return; }
    setBusy(true); setMessage("");
    try {
      const incoming = await labelsApi.uploadAudio(batch.classroom_id, batch.id, file);
      setAsset(incoming); setMessage("原声已归档，可按标签时间回听。"); onSaved();
    } catch (failure) { setMessage(failure instanceof Error ? failure.message : "原声上传未确认成功。"); }
    finally { setBusy(false); }
  }
  function range() {
    const audio = player.current;
    return trackWindow(startMs, endMs, 0, audio?.duration ?? 0);
  }
  function constrain() {
    const audio = player.current;
    if (!audio || !Number.isFinite(audio.duration)) return;
    const bounds = range();
    if (!bounds.available || !active) { audio.pause(); return; }
    if (audio.currentTime < bounds.start) audio.currentTime = bounds.start;
    if (audio.currentTime >= bounds.end) {
      audio.pause(); if (audio.currentTime > bounds.end) audio.currentTime = bounds.end;
    }
  }
  return <div className={styles.audio} onDragOver={(event) => {
    if (!asset && !busy) event.preventDefault();
  }} onDrop={(event) => {
    event.preventDefault(); if (asset || busy) return;
    setFile(event.dataTransfer.files[0] ?? null); setMessage("已选中拖入的文件，点击上传归档。");
  }}>
    <p>原声回听 · {timeLabel(startMs)}—{timeLabel(endMs)}</p>
    {asset ? <><audio ref={player} controls preload="metadata"
      aria-label="标签对应原始音频" src={batchAudioPath(batch.classroom_id, batch.id)}
      onLoadedMetadata={() => {
        const audio = player.current; if (!audio) return;
        const bounds = range();
        if (!bounds.available) { setMessage("原声未覆盖当前标签时间，不能回听此范围。"); return; }
        audio.currentTime = bounds.start;
        if (endMs > asset.duration_ms) setMessage("当前标签末尾超出音频时长，仅可回听已归档部分。");
      }} onPlay={() => {
        const audio = player.current;
        if (!audio || !active || !range().available) { audio?.pause(); return; }
        if (audio.currentTime >= range().end) audio.currentTime = range().start;
      }} onTimeUpdate={constrain} onSeeking={constrain}
      onError={() => setMessage("原声读取失败，请刷新后检查音频归档与课堂权限。")} />
      <p className={styles.muted}>会话起点为0毫秒，已归档原声不能覆盖。</p>
    </> : <><p>当前批次尚未上传原声，可直接选择或拖入对应会话的WAV文件。</p>
      <label>上传原始WAV（20MB、10分钟以内，8—48kHz，单声道或双声道）
        <input type="file" accept=".wav,audio/wav" disabled={busy}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
      <button type="button" disabled={!file || busy} onClick={() => void upload()}>
        {busy ? "正在归档…" : "上传当前批次原声"}</button>
      {file && <p className={styles.muted}>已选文件：{file.name}</p>}
    </>}
    <p className={styles.muted}>当前批次未提供分离音轨。</p>
    {message && <p role="status">{message}</p>}
  </div>;
}
