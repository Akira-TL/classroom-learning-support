"use client";

import { useEffect, useRef, useState } from "react";
import { deletionApi } from "../../lib/deletion/api";
import type { DeletionView } from "../../lib/deletion/api";
import { createAttempt, rememberAttempt, rememberTask } from "../../lib/deletion/attempts";
import type { DeletionAttempt } from "../../lib/deletion/attempts";
import type { Classroom } from "../../lib/types";
import { DeletionAttempts } from "./attempts";
import "../presentation/role-panels.css";

const localNames: Record<DeletionView["local_status"], string> = {
  pending: "待清理本机文件", complete: "本机清理完成", failed: "部分本机文件清理失败",
};
export function DeletionPanel({ classroom, onRemoved }: {
  classroom: Classroom | null; onRemoved: (deletedClassroomId: string) => Promise<void>;
}) {
  const scope = JSON.stringify([classroom?.id, classroom?.revision, classroom?.title]);
  const [form, setForm] = useState({ scope, confirmation: "", understood: false });
  const [attempts, setAttempts] = useState<DeletionAttempt[]>([]);
  const [tasks, setTasks] = useState<DeletionView[]>([]);
  const [taskId, setTaskId] = useState("");
  const [shownTask, setShownTask] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const attemptsRef = useRef<DeletionAttempt[]>([]);
  const operation = useRef(0);
  const active = useRef<number | null>(null);
  const mounted = useRef(true);
  const removedCallback = useRef(onRemoved);
  removedCallback.current = onRemoved;
  const task = tasks.find((item) => item.id === shownTask);
  const formCurrent = form.scope === scope;
  const unresolved = attempts.some((item) => item.classroom_id === classroom?.id && item.state !== "known");

  useEffect(() => {
    setForm({ scope, confirmation: "", understood: false });
  }, [scope]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; operation.current++; active.current = null; };
  }, []);
  function begin(): number | null {
    if (active.current !== null || !mounted.current) return null;
    const version = ++operation.current;
    active.current = version; setBusy(true); setError(""); setMessage("");
    return version;
  }
  function current(version: number): boolean {
    return mounted.current && active.current === version && operation.current === version;
  }
  function end(version: number) {
    if (current(version)) { active.current = null; setBusy(false); }
  }
  function saveAttempt(incoming: DeletionAttempt) {
    attemptsRef.current = rememberAttempt(attemptsRef.current, incoming);
    setAttempts(attemptsRef.current);
  }
  function remember(incoming: DeletionView) {
    setTasks((previous) => rememberTask(previous, incoming));
    setTaskId(incoming.id); setShownTask(incoming.id);
  }
  async function send(snapshot: DeletionAttempt) {
    const version = begin();
    if (version === null) return;
    const attempt = { ...snapshot, operation: version, state: "sending" as const, error: null };
    saveAttempt(attempt);
    try {
      const result = await deletionApi.create(attempt.classroom_id, attempt.request);
      if (!current(version)) return;
      if (result.classroom_id !== attempt.classroom_id) throw new Error("删除任务与原课堂不一致，未确认本次结果。");
      saveAttempt({ ...attempt, state: "known", task_id: result.id });
      remember(result);
      setMessage(`原课堂“${attempt.title}”的删除任务已取得，受控入口已关闭；请核对分别状态。`);
      try { await removedCallback.current(attempt.classroom_id); }
      catch (cause: unknown) {
        if (current(version)) setError(`任务已保留，但课堂列表刷新失败：${cause instanceof Error ? cause.message : "请手动刷新"}`);
      }
    } catch (cause: unknown) {
      if (!current(version)) return;
      const detail = cause instanceof Error ? cause.message : "原删除请求结果未知";
      saveAttempt({ ...attempt, state: "unknown", error: detail }); setError(detail);
    } finally { end(version); }
  }
  async function remove() {
    if (!classroom || !formCurrent || !form.understood || form.confirmation !== classroom.title
      || unresolved || active.current !== null) return;
    const snapshot = createAttempt(classroom.id, classroom.title, classroom.revision, crypto.randomUUID());
    await send(snapshot);
  }
  async function retryUnknown(snapshot: DeletionAttempt) {
    const latest = attemptsRef.current.find(
      (item) => item.request.idempotency_key === snapshot.request.idempotency_key,
    );
    if (!latest || latest.state !== "unknown") return;
    await send(latest);
  }
  async function inspect(id: string, retry = false) {
    const identity = id.trim();
    if (!identity) return;
    const version = begin();
    if (version === null) return;
    try {
      const result = retry ? await deletionApi.retry(identity) : await deletionApi.get(identity);
      if (!current(version)) return;
      if (result.id !== identity) throw new Error("返回的任务编号与查询目标不一致。");
      remember(result);
    } catch (cause: unknown) {
      if (current(version)) setError(cause instanceof Error ? cause.message : "删除任务读取失败");
    } finally { end(version); }
  }
  return <section className="support-panel deletion-panel" aria-label="课堂删除与资源清除">
    <p className="eyebrow">课堂资料管理</p><h3>删除与资源清除</h3>
    <p className="panel-intro">本机清理与供应方删除分别展示进度，任务状态可独立查询。</p>
    <details className="deletion-confirmation"><summary>删除当前课堂与关联资料</summary>
    <p className="privacy-note">删除会关闭本项目保存的课堂录音、发言、分析、练习、教学安排及学生和家长报告入口，
      并清除对应的本机文件。供应方删除尚未发起；已下载的离线副本无法远程收回。</p>
    {classroom ? <div>
      <div className="readonly-target"><span>本次操作对象</span><strong>{classroom.title}</strong>
        <small>课堂版本 {classroom.revision}</small></div>
      <label><input type="checkbox" checked={formCurrent && form.understood} disabled={busy}
        onChange={(event) => setForm((previous) => ({ scope, understood: event.target.checked,
          confirmation: previous.scope === scope ? previous.confirmation : "" }))} />
        我已理解删除范围和不可远程收回的限制</label>
      <label>手工输入完全相同的课堂名称以确认
        <input value={formCurrent ? form.confirmation : ""} autoComplete="off" maxLength={200} disabled={busy}
          onChange={(event) => setForm((previous) => ({ scope, confirmation: event.target.value,
            understood: previous.scope === scope && previous.understood }))} /></label>
      <button className="danger-text"
        disabled={busy || !formCurrent || !form.understood || form.confirmation !== classroom.title || unresolved}
        onClick={() => void remove()}>确认删除这堂课并清理资源</button>
      {unresolved && <p>这堂课已有未确认原请求，请先在下方用同一请求核对，不能为其另建删除请求。</p>}
    </div> : <p>选择课堂后可新建删除操作；切换或清空选择不会丢失下方原请求和已知任务。</p>}
    </details>
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    <DeletionAttempts attempts={attempts} busy={busy} onRetry={(item) => void retryUnknown(item)}
      onInspect={(id) => void inspect(id)} />
    <section className="deletion-query" aria-label="查询既有删除任务"><h4>查询删除进度</h4>
      <p>可复制任务编号留存。不将课堂名称、正文或任务编号写入本地存储；服务端只允许操作人查看。</p>
      <label>任务编号<input value={taskId} onChange={(event) => setTaskId(event.target.value)} disabled={busy} /></label>
      <button disabled={busy || !taskId.trim()} onClick={() => void inspect(taskId)}>查询任务</button>
    </section>
    {task && <section className="history-card deletion-task" aria-label="删除任务状态">
      <header className="panel-heading"><h4>清理任务状态</h4>
        <span className="basis-label">状态版本 {task.revision}</span></header>
      <p className="basis-label">建立时间：{new Date(task.created_at).toLocaleString("zh-CN")}</p>
      <div className="summary-metrics"><div><span>本机文件</span><h4>{localNames[task.local_status]}</h4>
        <p>剩余文件 {task.remaining_files} 个 · {task.local_complete ? "清理已完成" : "清理尚未完成"}</p></div>
      <div><span>供应方数据</span><h4>{task.external_status === "not_requested" ? "尚未请求删除" : "尚未确认"}</h4>
        <p>{task.external_pending ? "外部数据删除仍待处理" : "请核对供应方回执"}</p></div></div>
      <p>{task.notice}</p>
      <details className="audit-details"><summary>任务编号与对应课堂</summary>
        <p>任务：{task.id}</p><p>原课堂：{task.classroom_id}</p></details>
      {task.error && <p role="alert">{task.error}</p>}
      <button disabled={busy} onClick={() => void inspect(task.id)}>刷新状态</button>
      {!task.local_complete && <button disabled={busy} onClick={() => void inspect(task.id, true)}>
        重试清理剩余本机文件
      </button>}
    </section>}
  </section>;
}
