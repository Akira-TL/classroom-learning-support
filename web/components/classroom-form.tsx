"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { contentSchema, emptyClassroom, emptyQuestion } from "../lib/types";
import type { Classroom, ClassroomContent, Question } from "../lib/types";

export function ClassroomForm({ classroom, busy, onSave, onCancel }: {
  classroom: Classroom | null; busy: boolean;
  onSave: (content: ClassroomContent, idempotencyKey: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [content, setContent] = useState<ClassroomContent>(() => classroom ?? emptyClassroom());
  const [students, setStudents] = useState(content.students.join(", "));
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [error, setError] = useState("");

  function changeQuestion(index: number, update: Partial<Question>) {
    setContent((previous) => ({ ...previous, questions: previous.questions.map(
      (question, position) => position === index ? { ...question, ...update } : question,
    ) }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = contentSchema.safeParse({
      ...content, students: students.split(/[,，\s]+/).filter(Boolean),
    });
    if (!result.success) {
      setError(result.error.issues.map((item) => `${item.path.join(".")}：${item.message}`).join("；"));
      return;
    }
    setError("");
    await onSave(result.data, idempotencyKey);
  }

  return <form onSubmit={submit}>
    <h2>{classroom ? `修改课堂（当前版本 ${classroom.revision}）` : "创建课堂"}</h2>
    {error && <p role="alert">{error}</p>}
    <fieldset disabled={busy}>
      <legend>课堂准备</legend>
      <label>名称<input required maxLength={200} value={content.title}
        onChange={(event) => setContent({ ...content, title: event.target.value })} /></label>
      <label>日期<input required type="date" value={content.date}
        onChange={(event) => setContent({ ...content, date: event.target.value })} /></label>
      <label>教学目标<textarea required maxLength={2000} value={content.objective}
        onChange={(event) => setContent({ ...content, objective: event.target.value })} /></label>
      <label>虚构学生名单（用逗号分隔）<input required value={students}
        onChange={(event) => setStudents(event.target.value)} /></label>
      <p>仅接受 student-01 至 student-10，不输入真实学生姓名。</p>
      <label>材料来源<textarea required maxLength={1000} value={content.source}
        onChange={(event) => setContent({ ...content, source: event.target.value })} /></label>
      <label>使用授权说明<textarea required maxLength={2000} value={content.authorization}
        onChange={(event) => setContent({ ...content, authorization: event.target.value })} /></label>
      {content.questions.map((question, index) => <fieldset key={index}>
        <legend>题目 {index + 1}</legend>
        <label>题目标识<input required maxLength={80} value={question.id}
          onChange={(event) => changeQuestion(index, { id: event.target.value })} /></label>
        <label>题干<textarea required maxLength={6000} value={question.text}
          onChange={(event) => changeQuestion(index, { text: event.target.value })} /></label>
        <label>参考答案<textarea required maxLength={6000} value={question.reference_answer}
          onChange={(event) => changeQuestion(index, { reference_answer: event.target.value })} /></label>
        <label><input type="checkbox" checked={question.diagram_required}
          onChange={(event) => changeQuestion(index, { diagram_required: event.target.checked })} />
          需要图形上下文</label>
        <label>图形说明<textarea maxLength={4000} value={question.diagram_description ?? ""}
          onChange={(event) => changeQuestion(index, {
            diagram_description: event.target.value || null,
          })} /></label>
        <button type="button" disabled={content.questions.length === 1}
          onClick={() => setContent({ ...content, questions: content.questions.filter((_, i) => i !== index) })}>
          删除本题
        </button>
      </fieldset>)}
      <button type="button" disabled={content.questions.length >= 30} onClick={() => setContent({
        ...content, questions: [...content.questions, emptyQuestion(content.questions.length + 1)],
      })}>添加题目</button>
      <button type="submit">{busy ? "正在保存…" : "保存课堂"}</button>
      <button type="button" onClick={onCancel}>取消</button>
    </fieldset>
  </form>;
}
