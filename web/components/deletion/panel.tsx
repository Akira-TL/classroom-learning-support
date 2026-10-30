"use client";

import { useEffect, useRef, useState } from "react";
import { deletionApi } from "../../lib/deletion/api";
import type { DeletionView } from "../../lib/deletion/api";
import type { Classroom } from "../../lib/types";

const localNames: Record<DeletionView["local_status"], string> = {
  pending: "待清理本机文件", complete: "本机清理完成", failed: "部分本机文件清理失败",
};

export function DeletionPanel({ classroom, onRemoved }: {
  classroom: Classroom | null; onRemoved: () => Promise<void>;
}) {
  const [confirmation, setConfirmation] = useState("");
  const [understood, setUnderstood] = useState(false);
  const [task, setTask] = useState<DeletionView | null>(null);
  const [taskId, setTaskId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const pending = useRef({ signature: "", key: "" });
  const requestVersion = useRef(0);
  const classroomId = classroom?.id;
  const revision = classroom?.revision;
  const title = classroom?.title;

  useEffect(() => {
    setConfirmation(""); setUnderstood(false); pending.current = { signature: "", key: "" };
  }, [classroomId, revision, title]);

  function remember(incoming: DeletionView) {
    setTask((previous) => previous?.id === incoming.id && previous.revision > incoming.revision ? previous : incoming);
    setTaskId(incoming.id);
  }

  async function remove() {
    if (!classroom || !understood || confirmation !== classroom.title || busy) return;
    const version = ++requestVersion.current;
    const signature = JSON.stringify([classroom.id, classroom.revision, confirmation]);
    if (pending.current.signature !== signature) pending.current = { signature, key: crypto.randomUUID() };
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await deletionApi.create(classroom.id, {
        expected_revision: classroom.revision, confirmation, idempotency_key: pending.current.key,
      });
      if (version !== requestVersion.current) return;
      remember(result);
      setMessage("删除操作已建立，课堂受控入口已关闭。请查看下方本机与供应方的分别状态。");
      try { await onRemoved(); }
      catch (cause: unknown) {
        setError(`删除任务已保留，但课堂列表刷新失败：${cause instanceof Error ? cause.message : "请手动刷新列表"}`);
      }
    } catch (cause: unknown) {
      if (version === requestVersion.current) setError(cause instanceof Error ? cause.message : "删除未确认成功");
    } finally { if (version === requestVersion.current) setBusy(false); }
  }

  async function inspect(id: string, retry = false) {
    const identity = id.trim();
    if (!identity || busy) return;
    const version = ++requestVersion.current;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = retry ? await deletionApi.retry(identity) : await deletionApi.get(identity);
      if (version === requestVersion.current) remember(result);
    } catch (cause: unknown) {
      if (version === requestVersion.current) setError(cause instanceof Error ? cause.message : "删除任务读取失败");
    } finally { if (version === requestVersion.current) setBusy(false); }
  }

  return <section aria-label="课堂删除与资源清除">
    <h2>课堂删除与资源清除</h2>
    <p>删除会关闭本项目保存的课堂录音、发言、分析、练习、教学安排及学生和家长报告入口，
      并清除对应的本机文件。供应方删除尚未发起；已下载的离线副本无法远程收回。</p>
    {classroom ? <div>
      <p>当前课堂：{classroom.title} · 版本 {classroom.revision}</p>
      <label><input type="checkbox" checked={understood} disabled={busy}
        onChange={(event) => setUnderstood(event.target.checked)} />我已理解删除范围和不可远程收回的限制</label>
      <label>手工输入完全相同的课堂名称以确认
        <input value={confirmation} autoComplete="off" maxLength={200} disabled={busy}
          onChange={(event) => setConfirmation(event.target.value)} /></label>
      <button disabled={busy || !understood || confirmation !== classroom.title} onClick={() => void remove()}>
        确认删除这堂课并清理资源
      </button>
    </div> : <p>选择课堂后可发起删除；已有删除任务仍可在下方查询。</p>}
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    <section aria-label="查询既有删除任务"><h3>查询删除进度</h3>
      <p>可复制任务编号留存。这里不自动保存课堂名称、正文或任务编号到浏览器；服务端只允许操作人查看。</p>
      <label>任务编号<input value={taskId} onChange={(event) => setTaskId(event.target.value)} disabled={busy} /></label>
      <button disabled={busy || !taskId.trim()} onClick={() => void inspect(taskId)}>查询任务</button>
    </section>
    {task && <section aria-label="删除任务状态">
      <p>任务编号：{task.id} · 状态版本 {task.revision}</p>
      <p>建立时间：{new Date(task.created_at).toLocaleString("zh-CN")}</p>
      <p>本机：{localNames[task.local_status]}；{task.local_complete ? "本机清理已完成" : "本机清理尚未完成"}，
        剩余文件 {task.remaining_files} 个。</p>
      <p>供应方：{task.external_status === "not_requested" ? "未发起外部删除请求" : "尚未确认"}；
        {task.external_pending ? "外部数据删除仍待处理" : "请核对供应方回执"}。</p>
      <p>{task.notice}</p>
      {task.error && <p role="alert">{task.error}</p>}
      <button disabled={busy} onClick={() => void inspect(task.id)}>刷新状态</button>
      {!task.local_complete && <button disabled={busy} onClick={() => void inspect(task.id, true)}>
        重试清理剩余本机文件
      </button>}
    </section>}
  </section>;
}
