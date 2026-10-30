"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { questionStatus, reportsApi, reportStatus } from "../../lib/reports";
import type { ParentQuestion, ParentReport } from "../../lib/reports";

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

  return <section aria-label="家长学习反馈">
    <h2>家长学习反馈</h2>
    <p>演示账号仅绑定 student-01；只显示教师向该学生家长发布的内容，不提供课堂原音频。</p>
    <button disabled={loading || busy} onClick={() => void refresh()}>刷新报告及有效状态</button>
    {loading && <p role="status">正在核对报告状态…</p>}
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {!loading && reports.length === 0 && <p>尚无绑定学生的已发布报告；请等待教师发布。</p>}
    <ul>{reports.map((report) => <li key={report.id}>
      <button disabled={busy} onClick={() => setSelectedId(report.id)}>{report.student_id}：{reportStatus[report.status]}
        （报告版本 {report.revision}）</button>
    </li>)}</ul>
    {selected && <article>
      <h3>学生 {selected.student_id} 的反馈</h3>
      <p>{reportStatus[selected.status]} · {new Date(selected.published_at).toLocaleString("zh-CN")}</p>
      {selected.status === "published" ? <>
        <h4>学习摘要</h4><p>{selected.summary}</p>
        <h4>家庭活动</h4><p>{selected.home_activity}</p>
        <label>向教师提问<textarea value={text} maxLength={3000} disabled={busy}
          onChange={(event) => {
            const value = event.target.value;
            setDrafts((previous) => ({ ...previous, [selectedId]: value })); questionKey.current = null;
          }} /></label>
        <button disabled={busy || !text.trim()} onClick={() => void submit()}>提交疑问</button>
      </> : <p>此报告正文已停止提供，请等待教师发布新版；仍可查看此前疑问的处理结果。</p>}
      <h4>此前疑问及教师回复</h4>
      <button disabled={busy} onClick={() => void refreshQuestions()}>刷新教师回复</button>
      {questions.length === 0 && <p>暂无疑问。</p>}
      {questions.map((question) => <article key={question.id}>
        <p>{question.text} · {questionStatus[question.status]}</p>
        {question.response && <p>教师回复：{question.response}</p>}
      </article>)}
    </article>}
    <p>站内撤回会停止旧报告读取；已保存到个人设备的离线副本不能远程收回，请核对当前状态。</p>
  </section>;
}
