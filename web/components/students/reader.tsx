"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../lib/api";
import { levelNames } from "../../lib/exercises";
import { studentsApi } from "../../lib/students/api";
import { feedbackNames, reportNames } from "../../lib/students/types";
import type { ReportSummary, StudentFeedback, StudentReport } from "../../lib/students/types";

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

  return <section>
    <h2>我的学习反馈与练习</h2>
    <button onClick={() => void refresh()}>刷新报告列表</button>
    {reports.length === 0 && <p>暂无已发布的个人报告。</p>}
    {reports.map((item) => <p key={item.id}><button aria-pressed={selected === item.id} onClick={() => {
      if (selected === item.id) return;
      sequence.current += 1; setSelected(item.id); setReport(null); setFeedback([]); setNotice(""); setError("");
    }}>报告 {item.id.slice(0, 8)} · 版本 {item.revision} · {reportNames[item.status]}</button></p>)}
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert">{error}</p>}
    {report && <article>
      <h3>教师反馈</h3><p>{report.feedback}</p>
      {report.exercises.map((item) => <section key={item.level}><h4>{levelNames[item.level]}</h4>
        <p>{item.question}</p><details><summary>查看答案与解释</summary>
          <p>{item.answer}</p><p>{item.explanation}</p></details></section>)}
      <label>反馈类型<select value={kind} onChange={(event) => editDraft({
        kind: event.target.value === "correction" ? "correction" : "exercise_feedback",
      })}><option value="exercise_feedback">练习反馈</option><option value="correction">申请核对记录</option></select></label>
      <label>反馈内容<textarea maxLength={4000} value={text}
        onChange={(event) => editDraft({ text: event.target.value })} /></label>
      <button disabled={busy || !text.trim()} onClick={() => void submit()}>提交给教师</button>
    </article>}
    {selected && <section><h3>我的反馈与教师回复</h3>
      {feedback.length === 0 && <p>还没有提交反馈。</p>}
      {feedback.map((item) => <article key={item.id}><p>{item.text}</p>
        <p>针对原报告版本 {item.report_revision} · {feedbackNames[item.status]}</p>
        {item.response && <p>教师回复：{item.response}</p>}</article>)}
    </section>}
  </section>;
}
