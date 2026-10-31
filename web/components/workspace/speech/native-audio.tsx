"use client";

import { useEffect, useRef, useState } from "react";
import type { Utterance } from "../../../lib/speech";
import { trackNames } from "../../../lib/speech/native";
import { alignedPosition, trackWindow } from "./track-time";
import styles from "../workspace.module.css";

export function NativeAudio({ classroomId, utterance, active }: {
  classroomId: string; utterance: Utterance; active: boolean;
}) {
  const tracks = utterance.native_event?.audio_ref ?? [];
  const [choice, setChoice] = useState(tracks[0]?.id ?? "");
  const [message, setMessage] = useState("");
  const [ready, setReady] = useState(false);
  const player = useRef<HTMLAudioElement>(null);
  const sessionTime = useRef(utterance.start_ms);
  const track = tracks.find((item) => item.id === choice) ?? tracks[0];
  useEffect(() => { if (!active) player.current?.pause(); }, [active]);
  if (!track) return <p className={styles.notice}>上游尚未提供可回听音轨。</p>;
  const path = `/api/classrooms/${encodeURIComponent(classroomId)}/speech/`
    + `${encodeURIComponent(utterance.session_id)}/${encodeURIComponent(utterance.segment_id)}`
    + `/tracks/${encodeURIComponent(track.id)}`;
  function constrain() {
    const audio = player.current;
    if (!audio || !track || !Number.isFinite(audio.duration)) return;
    const range = trackWindow(utterance.start_ms, utterance.end_ms, track.offset_ms, audio.duration);
    if (!range.available) { audio.pause(); return; }
    if (audio.currentTime < range.start) audio.currentTime = range.start;
    if (audio.currentTime >= range.end) { audio.pause(); audio.currentTime = range.end; }
    sessionTime.current = audio.currentTime * 1000 + track.offset_ms;
  }
  return <div className={styles.audio}>
    <div role="group" aria-label="选择对照音轨" className={styles.actions}>
      {tracks.map((item, index) => <button key={item.id} type="button" aria-pressed={item.id === track.id}
        onClick={() => {
          if (item.id === track.id) return;
          player.current?.pause(); setReady(false); setMessage(""); setChoice(item.id);
        }}>{trackNames[item.kind]}{item.kind === "separated" ? ` ${index}` : ""}</button>)}
    </div>
    <p className={styles.muted}>按同一发言范围对照；切换保留会话时间，点击播放继续回听。</p>
    <audio key={track.id} ref={player} controls preload="metadata" src={path}
      aria-label={trackNames[track.kind]} onLoadedMetadata={() => {
        const audio = player.current;
        if (!audio) return;
        const range = trackWindow(utterance.start_ms, utterance.end_ms, track.offset_ms, audio.duration);
        setReady(range.available);
        if (!range.available) { setMessage("该音轨没有覆盖当前发言的时间范围，不能用于对照。"); return; }
        const position = alignedPosition(sessionTime.current, track.offset_ms, range.start, range.end);
        audio.currentTime = position >= range.end ? range.start : position;
        setMessage(range.end - range.start < (utterance.end_ms - utterance.start_ms) / 1000 - 0.05
          ? "该音轨仅覆盖部分发言，缺失部分不能回听。" : "");
      }} onTimeUpdate={constrain} onSeeking={constrain} onPlay={() => {
        if (!ready || !active) player.current?.pause();
        const audio = player.current;
        if (!audio) return;
        const range = trackWindow(utterance.start_ms, utterance.end_ms, track.offset_ms, audio.duration);
        if (audio.currentTime >= range.end) audio.currentTime = range.start;
      }} onError={() => { setReady(false); setMessage("音轨读取失败或尚未归档。可刷新后重试，当前不能确认可回听。"); }} />
    {message && <p role="status">{message}</p>}
    {track.note && <p className={styles.muted}>{track.note}</p>}
    {!tracks.some((item) => item.kind === "separated") && <p className={styles.muted}>上游未提供分离音轨。</p>}
  </div>;
}
