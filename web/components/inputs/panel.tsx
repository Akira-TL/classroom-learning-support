"use client";

import { useEffect, useRef, useState } from "react";
import { inputsApi } from "../../lib/inputs/api";
import { FileStream } from "../../lib/inputs/file-stream";
import { MicrophoneCapture } from "../../lib/inputs/microphone";
import { inputStatusNames } from "../../lib/inputs/types";
import type { CaptureCallbacks, CaptureController, InputSession } from "../../lib/inputs/types";
import { parseWav } from "../../lib/inputs/wav";

export function InputPanel({ classroomId }: { classroomId: string }) {
  const [sessions, setSessions] = useState<InputSession[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<"file_stream" | "microphone" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [wallMilliseconds, setWallMilliseconds] = useState(0);
  const controller = useRef<CaptureController | null>(null);
  const generation = useRef(0);
  const startedAt = useRef<number | null>(null);
  const activeSession = useRef<InputSession | null>(null);

  useEffect(() => {
    let active = true;
    setMode(null); setBusy(false); setSessions([]); startedAt.current = null; activeSession.current = null;
    setWallMilliseconds(0);
    inputsApi.list(classroomId).then((values) => { if (active) setSessions(values); })
      .catch((failure: unknown) => { if (active) setError(failure instanceof Error ? failure.message : "采集记录读取失败。"); });
    const stop = () => { generation.current++; void controller.current?.stop(true); controller.current = null; };
    const leave = () => { stop(); setMode(null); setBusy(false); setNotice("页面离开时已停止本机采集。"); };
    window.addEventListener("pagehide", leave);
    return () => { active = false; window.removeEventListener("pagehide", leave); stop(); };
  }, [classroomId]);
  useEffect(() => {
    if (!mode) return;
    const timer = setInterval(() => {
      if (startedAt.current !== null) setWallMilliseconds(performance.now() - startedAt.current);
    }, 200);
    return () => clearInterval(timer);
  }, [mode]);

  function callbacks(epoch: number): CaptureCallbacks {
    return {
      session(value) {
        if (generation.current !== epoch) return;
        if (startedAt.current === null) startedAt.current = performance.now();
        activeSession.current = value;
        setSessions((previous) => {
          const old = previous.find((item) => item.id === value.id);
          return old ? previous.map((item) => item.id === value.id ? value : item) : [...previous, value];
        });
      },
      error(message) { if (generation.current === epoch) setError(message); },
      stopped() {
        if (generation.current !== epoch) return;
        if (startedAt.current !== null) setWallMilliseconds(performance.now() - startedAt.current);
        controller.current = null; setMode(null); setBusy(false);
      },
    };
  }
  async function start(inputMode: "file_stream" | "microphone") {
    const epoch = ++generation.current;
    setBusy(true); setError(""); setNotice(""); startedAt.current = null; activeSession.current = null;
    setWallMilliseconds(0); setMode(inputMode);
    try {
      if (inputMode === "microphone") {
        const capture = new MicrophoneCapture(classroomId, callbacks(epoch));
        controller.current = capture;
        setNotice("等待麦克风权限或设备，可点击取消。拒绝授权不会生成识别结果。");
        await capture.start();
        if (generation.current === epoch && controller.current) {
          setNotice("麦克风权限已取得，本机采集已开始；识别服务仍未连接。");
        }
      } else {
        if (!file) throw new Error("请先选择 PCM16 单声道 WAV 文件。");
        if (file.size > 20 * 1024 * 1024) throw new Error("文件超过20MiB限制。");
        const wav = parseWav(await file.arrayBuffer());
        if (generation.current !== epoch) return;
        const capture = new FileStream(classroomId, wav, callbacks(epoch));
        controller.current = capture; await capture.start();
        setNotice("按真实样本时长发送，不进行转写或定位。每次开始均新建会话。");
      }
    } catch (failure) {
      if (generation.current === epoch) {
        setError(failure instanceof Error ? failure.message : "音频输入无法启动。");
        await controller.current?.stop(true); controller.current = null; setMode(null);
      }
    } finally { if (generation.current === epoch) setBusy(false); }
  }
  async function stop() {
    const current = controller.current;
    setBusy(true);
    if (!current) { generation.current++; setMode(null); setBusy(false); return; }
    await current.stop();
    setMode(null); setBusy(false); setNotice("已停止本次输入。等待权限已取消时，晚到的设备授权会立即关闭。");
  }
  async function state(action: "pause" | "resume") {
    const current = controller.current;
    if (!(current instanceof FileStream)) return;
    setBusy(true); setError("");
    try { if (action === "pause") await current.pause(); else await current.resume(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "文件控制状态未确认。"); }
    finally { setBusy(false); }
  }
  async function refresh() {
    setBusy(true); setError("");
    try { setSessions(await inputsApi.list(classroomId)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "采集记录读取失败。"); }
    finally { setBusy(false); }
  }
  async function recover(session: InputSession) {
    setBusy(true); setError("");
    try {
      const value = await inputsApi.recover(classroomId, session.id);
      setSessions((previous) => previous.map((item) => item.id === value.id ? value : item));
      setNotice("已请求手动恢复本机归档；没有连接识别服务。");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "归档恢复未确认。"); }
    finally { setBusy(false); }
  }
  return <section aria-label="本机音频采集与传输诊断">
    <h3>本机音频采集与传输诊断</h3>
    <p>识别服务未连接。这里只传输并归档本机音频，不会生成文字、位置或学生身份，不能据此通过真实语音联调验收。</p>
    {error && <p role="alert">{error}</p>}
    <p role="status" aria-live="polite">{notice}</p>
    <details><summary>文件按真实速度发送</summary>
      <label>PCM16 单声道 WAV（8—48kHz）<input type="file" accept=".wav,audio/wav" disabled={Boolean(mode) || busy}
        onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
      <button disabled={Boolean(mode) || busy || !file} onClick={() => void start("file_stream")}>开始文件输入</button>
      <button disabled={busy || mode !== "file_stream" || activeSession.current?.status !== "recording"}
        onClick={() => void state("pause")}>等待在途确认后暂停</button>
      <button disabled={busy || mode !== "file_stream" || activeSession.current?.status !== "paused"}
        onClick={() => void state("resume")}>从样本游标继续</button>
    </details>
    <details><summary>麦克风实时输入</summary>
      <p>点击才会请求权限；麦克风停止后重新开始会创建新会话，不伪装成连续录音。</p>
      <button disabled={Boolean(mode) || busy} onClick={() => void start("microphone")}>请求麦克风并开始</button>
    </details>
    <button disabled={!mode} onClick={() => void stop()}>停止输入／取消等待麦克风权限</button>
    <button disabled={busy} onClick={() => void refresh()}>刷新归档状态</button>
    <p>本次会话墙钟历时：{(wallMilliseconds / 1000).toFixed(2)} 秒。
      从会话创建确认起计，含网络、暂停与归档等待，不等同音频时长。</p>
    {sessions.length === 0 && <p>暂无本机音频输入会话。</p>}
    {sessions.map((session) => <article key={session.id}>
      <h4>{session.input_mode === "microphone" ? "麦克风" : "文件流"}：{inputStatusNames[session.status]}</h4>
      <p>会话：{session.id}；处理模式：仅采集归档；识别连接：未连接。</p>
      <p>实际采样率 {session.sample_rate}Hz，单声道 PCM16；已接收 {session.received_samples} 个样本，
        音频时长 {(session.received_samples / session.sample_rate).toFixed(3)} 秒；下一帧序号 {session.expected_sequence}。</p>
      {session.error && <p role="alert">{session.error}</p>}
      {session.status === "finishing" && <button disabled={busy} onClick={() => void recover(session)}>
        手动恢复归档（仅采集，不连接识别）
      </button>}
      {session.status === "ended" && session.audio_asset
        ? <audio controls preload="none" src={inputsApi.audio(classroomId, session.id)} />
        : <p>尚无可播放的完整归档；中断和失败不冒充成功。</p>}
    </article>)}
  </section>;
}
