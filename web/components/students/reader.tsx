"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../lib/api";
import { levelNames } from "../../lib/exercises";
import { studentsApi } from "../../lib/students/api";
import { feedbackNames, reportNames } from "../../lib/students/types";
import type { ReportSummary, StudentFeedback, StudentReport } from "../../lib/students/types";
import "../presentation/role-panels.css";

interface ReaderDraft { text: string; kind: StudentFeedback["kind"]; }

export function StudentReader() {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [report, setReport] = useState<StudentReport | null>(null);
  const [feedback, setFeedback] = useState<StudentFeedback[]>([]);
  const [drafts, setDrafts] = useState<Record<string, ReaderDraft>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [level, setLevel] = useState<"concept" | "explanation" | "transfer">("concept");
  const sequence = useRef(0);
  const pending = useRef({ signature: "", key: "" });
  const { text, kind } = drafts[selected] ?? { text: "", kind: "exercise_feedback" };
  function editDraft(change: Partial<ReaderDraft>) {
    setDrafts((previous) => ({ ...previous, [selected]: { text, kind, ...change } }));
  }

  const refresh = useCallback(async () => {
    try { setReports(await studentsApi.list()); }
    catch (cause: unknown) { setError(cause instanceof Error ? cause.message : "报告列表加载失败"); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    const read = async () => {
      const generation = ++sequence.current;
      const [body, history] = await Promise.allSettled([studentsApi.read(selected), studentsApi.feedback(selected)]);
      if (!active || generation !== sequence.current) return;
      if (body.status === "fulfilled") { setReport(body.value); setNotice(""); }
      else {
        setReport(null);
        const cause: unknown = body.reason;
        setNotice(cause instanceof ApiError && cause.status === 410
          ? "报告已撤回或依据变化，正文已隐藏；你仍可查看已有反馈和教师回复。"
          : cause instanceof Error ? cause.message : "报告读取失败");
      }
      if (history.status === "fulfilled") setFeedback(history.value);
      else setError(history.reason instanceof Error ? history.reason.message : "反馈历史加载失败");
    };
    void read();
    const timer = setInterval(() => { void read(); void refresh(); }, 10000);
    return () => { active = false; clearInterval(timer); };
  }, [selected, refresh]);

  async function submit() {
    if (!report || !text.trim()) return;
    const signature = JSON.stringify({ id: report.id, text, kind });
    if (pending.current.signature !== signature) pending.current = { signature, key: crypto.randomUUID() };
    setBusy(true); setError("");
    try {
      const item = await studentsApi.submit(report.id, kind, text, pending.current.key);
      setFeedback((items) => [...items.filter((entry) => entry.id !== item.id), item]);
      setDrafts((previous) => previous[report.id]?.text === text && previous[report.id]?.kind === kind
        ? { ...previous, [report.id]: { text: "", kind } } : previous);
      setNotice("反馈已提交，等待教师处理。");
    } catch (cause: unknown) {
      if (cause instanceof ApiError && cause.status === 410) setReport(null);
      setError(cause instanceof Error ? cause.message : "提交失败，填写内容已保留");
    } finally { setBusy(false); }
  }

  return <section className="role-panel student-reader" aria-label="我的学习反馈">
    <header className="panel-heading"><div><p className="eyebrow">学生端 · 模拟资料</p>
      <h2>我的学习反馈</h2></div><button className="quiet-button" onClick={() => void refresh()}>刷新报告</button></header>
    <p className="panel-intro">阅读教师确认的反馈，完成练习，也可以把疑问告诉教师。</p>
    {reports.length === 0 && <div className="empty-state">暂无个人报告，教师发布后会显示在这里。</div>}
    <nav className="report-picker" aria-label="选择学习报告">
    {reports.map((item, index) => <button key={item.id} aria-pressed={selected === item.id} onClick={() => {
      if (selected === item.id) return;
      sequence.current += 1; setSelected(item.id); setReport(null); setFeedback([]); setNotice(""); setError("");
    }}>学习报告 {index + 1}<span className={`status-badge status-${item.status}`}>{reportNames[item.status]}</span>
      <small>版本 {item.revision}</small></button>)}
    </nav>
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert">{error}</p>}
    {report && <article className="reading-card">
      <div className="feedback-highlight"><span className="status-badge status-published">教师已发布</span>
        <h3>教师给我的反馈</h3><p>{report.feedback}</p></div>
      <div className="level-switch" role="group" aria-label="练习层次">
        {report.exercises.map((item) => <button key={item.level} aria-pressed={level === item.level}
          onClick={() => setLevel(item.level)}>{levelNames[item.level]}</button>)}
      </div>
      {report.exercises.filter((item) => item.level === level).map((item) =>
        <section className="exercise-reading" key={item.level}><h4>{levelNames[item.level]}</h4>
        <p className="question-text">{item.question}</p><details><summary>查看答案与解释</summary>
          <h5>参考答案</h5><p>{item.answer}</p><h5>解释</h5><p>{item.explanation}</p></details></section>)}
      <h3>我的疑问</h3>
      <label>反馈类型<select value={kind} onChange={(event) => editDraft({
        kind: event.target.value === "correction" ? "correction" : "exercise_feedback",
      })}><option value="exercise_feedback">练习反馈</option><option value="correction">申请核对记录</option></select></label>
      <label>反馈内容<textarea maxLength={4000} value={text} placeholder="写下你对练习的疑问，或需要教师核对的记录…"
        onChange={(event) => editDraft({ text: event.target.value })} /></label>
      <button className="primary-button" disabled={busy || !text.trim()} onClick={() => void submit()}>
        {kind === "correction" ? "申请核对记录" : "提交反馈"}</button>
      <details className="audit-details"><summary>报告版本与来源记录</summary>
        <p>报告编号：{report.id}</p><p>教师发布版本：{report.revision}</p></details>
    </article>}
    {selected && <section className="response-history"><h3>我的反馈与教师回复</h3>
      {feedback.length === 0 && <p>还没有提交反馈。</p>}
      {feedback.map((item) => <article className="history-card" key={item.id}>
        <span className={`status-badge status-${item.status}`}>{feedbackNames[item.status]}</span><p>{item.text}</p>
        <small>针对原报告版本 {item.report_revision}</small>
        {item.response && <p className="teacher-response">教师回复：{item.response}</p>}</article>)}
    </section>}
  </section>;
}
