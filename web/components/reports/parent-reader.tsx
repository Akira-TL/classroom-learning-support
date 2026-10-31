"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { questionStatus, reportsApi, reportStatus } from "../../lib/reports";
import type { ParentQuestion, ParentReport } from "../../lib/reports";
import "../presentation/role-panels.css";

export function ParentReader() {
  const [reports, setReports] = useState<ParentReport[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [questions, setQuestions] = useState<ParentQuestion[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const questionKey = useRef<string | null>(null);
  const alive = useRef(false);
  const reportRequest = useRef(0);
  const questionRequest = useRef(0);
  const text = drafts[selectedId] ?? "";
  const selected = reports.find((report) => report.id === selectedId);
  const refresh = useCallback(async () => {
    const generation = ++reportRequest.current;
    setLoading(true); setError("");
    try {
      const incoming = await reportsApi.mine();
      if (alive.current && generation === reportRequest.current) setReports(incoming);
    }
    catch (failure) {
      if (!alive.current || generation !== reportRequest.current) return;
      setReports([]);
      setError(failure instanceof Error ? failure.message : "家长报告读取失败。");
    } finally { if (alive.current && generation === reportRequest.current) setLoading(false); }
  }, []);

  useEffect(() => {
    alive.current = true; void refresh();
    const timer = setInterval(() => void refresh(), 10000);
    return () => { alive.current = false; clearInterval(timer); };
  }, [refresh]);
  useEffect(() => {
    setSelectedId(new URLSearchParams(window.location.search).get("parent_report") ?? "");
  }, []);
  useEffect(() => {
    let active = true;
    setQuestions([]); questionKey.current = null;
    async function read() {
      if (!selectedId) return;
      const generation = ++questionRequest.current;
      try {
        const items = await reportsApi.questions(selectedId);
        if (active && generation === questionRequest.current) setQuestions((previous) => items.map((item) => {
          const old = previous.find((entry) => entry.id === item.id);
          return old && old.revision > item.revision ? old : item;
        }));
      } catch (failure: unknown) {
        if (active) setError(failure instanceof Error ? failure.message : "疑问读取失败。");
      }
    }
    void read();
    const timer = setInterval(() => void read(), 10000);
    return () => { active = false; clearInterval(timer); questionRequest.current += 1; };
  }, [selectedId]);

  async function submit() {
    if (!selected || !text.trim()) return;
    questionKey.current ??= crypto.randomUUID();
    setBusy(true); setError(""); setNotice("");
    try {
      const incoming = await reportsApi.ask(selected.id, text.trim(), questionKey.current);
      questionRequest.current += 1;
      setQuestions((items) => items.some((item) => item.id === incoming.id) ? items : [...items, incoming]);
      setNotice("疑问已提交，等待教师处理。");
      setDrafts((previous) => previous[selected.id] === text ? { ...previous, [selected.id]: "" } : previous);
      questionKey.current = null;
    } catch (failure) {
      await refresh();
      setError(failure instanceof Error ? failure.message : "提交未确认成功，可重试同一次请求。");
    } finally { setBusy(false); }
  }

  async function refreshQuestions() {
    if (!selectedId) return;
    const generation = ++questionRequest.current;
    try {
      const items = await reportsApi.questions(selectedId);
      if (alive.current && generation === questionRequest.current) setQuestions((previous) => items.map((item) => {
        const old = previous.find((entry) => entry.id === item.id);
        return old && old.revision > item.revision ? old : item;
      }));
    }
    catch (failure) {
      if (alive.current) setError(failure instanceof Error ? failure.message : "疑问读取失败。");
    }
  }

  return <section className="role-panel parent-reader" aria-label="家长学习反馈">
    <header className="panel-heading"><div><p className="eyebrow">家长端 · 模拟资料</p>
      <h2>孩子的学习反馈</h2></div>
      <button className="quiet-button" disabled={loading || busy} onClick={() => void refresh()}>刷新报告状态</button>
    </header><p className="panel-intro">教师筛选后的学习摘要与家庭活动，仅向绑定家长提供。</p>
    {loading && <p role="status">正在核对报告状态…</p>}
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {!loading && reports.length === 0 && <div className="empty-state">尚无绑定学生的已发布报告，请等待教师发布。</div>}
    <nav className="report-picker" aria-label="选择家长报告">{reports.map((report, index) =>
      <button key={report.id} aria-pressed={selectedId === report.id} disabled={busy}
        onClick={() => setSelectedId(report.id)}>学习报告 {index + 1}
        <span className={`status-badge status-${report.status}`}>{reportStatus[report.status]}</span>
        <small>版本 {report.revision}</small></button>)}</nav>
    {selected && <article className="reading-card">
      <p className="muted">{new Date(selected.published_at).toLocaleString("zh-CN")}</p>
      {selected.status === "published" ? <>
        <div className="feedback-highlight"><span className="status-badge status-published">教师已发布</span>
          <h3>学习摘要</h3><p>{selected.summary}</p></div>
        <section className="home-activity"><h3>家庭活动</h3><p>{selected.home_activity}</p></section>
        <label>向教师提问<textarea value={text} maxLength={3000} disabled={busy}
          placeholder="写下希望进一步了解的问题…"
          onChange={(event) => {
            const value = event.target.value;
            setDrafts((previous) => ({ ...previous, [selectedId]: value })); questionKey.current = null;
          }} /></label>
        <button className="primary-button" disabled={busy || !text.trim()} onClick={() => void submit()}>提交疑问</button>
      </> : <div className="empty-state warning-state"><h3>旧报告正文已停止提供</h3>
        <p>请等待教师发布新版，仍可查看此前疑问的处理结果。</p></div>}
      <header className="panel-heading"><h3>教师回复</h3>
        <button className="quiet-button" disabled={busy} onClick={() => void refreshQuestions()}>刷新回复</button></header>
      {questions.length === 0 && <p>暂无疑问。</p>}
      {questions.map((question) => <article className="history-card" key={question.id}>
        <span className={`status-badge status-${question.status}`}>{questionStatus[question.status]}</span>
        <p>{question.text}</p>
        {question.response && <p className="teacher-response">教师回复：{question.response}</p>}
      </article>)}
      <details className="audit-details"><summary>报告版本与绑定信息</summary>
        <p>报告编号：{selected.id}，版本 {selected.revision}</p>
        <p>当前演示绑定：{selected.student_id}；此入口不提供课堂原音频。</p></details>
    </article>}
    <p className="privacy-note">站内撤回会停止旧报告读取；已保存到个人设备的离线副本不能远程收回，请核对当前状态。</p>
  </section>;
}
