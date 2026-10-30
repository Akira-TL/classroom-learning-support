"use client";

import { useEffect, useState } from "react";
import { ClassroomForm } from "../components/classroom-form";
import { LoginForm } from "../components/login-form";
import { QuestionDiagram } from "../components/diagrams/question";
import { SpeechPanel } from "../components/speech-panel";
import { StudentReader } from "../components/students/reader";
import { StudentFeedbackQueue } from "../components/students/feedback-queue";
import { ManualExercises } from "../components/manual-exercises/panel";
import { AdminOverview } from "../components/overview/panel";
import { ApiError, api } from "../lib/api";
import type { Classroom, ClassroomContent, User } from "../lib/types";

const roleNames: Record<User["role"], string> = {
  teacher: "教师", student: "学生", parent: "家长", admin: "管理者",
};

export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [selected, setSelected] = useState<Classroom | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [formKey, setFormKey] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function report(failure: unknown) {
    if (failure instanceof ApiError && failure.status === 401) {
      setUser(null); setClassrooms([]); setSelected(null); setFormOpen(false);
    }
    setError(failure instanceof Error ? failure.message : "操作失败，未确认成功。");
  }

  useEffect(() => {
    let active = true;
    async function restore() {
      try {
        const current = await api.me();
        const list = current.role === "teacher" ? await api.classrooms() : [];
        if (active) { setUser(current); setClassrooms(list); }
      } catch (failure) {
        if (active && !(failure instanceof ApiError && failure.status === 401)) report(failure);
      } finally { if (active) setBusy(false); }
    }
    void restore();
    return () => { active = false; };
  }, []);

  async function perform(action: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (failure) { report(failure); } finally { setBusy(false); }
  }

  async function login(username: string, password: string) {
    await perform(async () => {
      const current = await api.login(username, password);
      setUser(current);
      setClassrooms(current.role === "teacher" ? await api.classrooms() : []);
      setNotice("登录成功。账号角色和课堂权限由服务端确定。");
    });
  }

  async function save(content: ClassroomContent, key: string) {
    await perform(async () => {
      const saved = selected
        ? await api.update(selected.id, content, selected.revision)
        : await api.create(content, key);
      setSelected(saved); setFormOpen(false);
      setClassrooms(await api.classrooms());
      setNotice(`课堂已保存，版本 ${saved.revision}。`);
    });
  }

  function openForm(classroom: Classroom | null) {
    setSelected(classroom); setFormOpen(true); setFormKey((value) => value + 1);
  }

  return <main>
    <h1>课堂学习支持 · 功能验证</h1>
    <p className="notice">当前页面验证功能与数据，尚不是最终视觉方案。三版效果图将在功能阶段后提供选择。</p>
    {error && <p role="alert">{error}</p>}
    <p role="status" aria-live="polite">{busy ? "操作进行中…" : notice}</p>
    {!user ? <LoginForm busy={busy} onLogin={login} /> : <>
      <p>当前账号：{user.id}；角色：{roleNames[user.role]}</p>
      <button disabled={busy} onClick={() => void perform(async () => {
        const current = await api.me(); setUser(current); setNotice("当前会话有效。");
      })}>检查当前会话</button>
      <button disabled={busy} onClick={() => void perform(async () => {
        await api.logout(); setUser(null); setClassrooms([]); setSelected(null); setFormOpen(false);
        setNotice("已退出登录。");
      })}>退出登录</button>
      {user.role === "student" ? <StudentReader key={user.id} />
        : user.role === "admin" ? <AdminOverview key={user.id} />
        : user.role !== "teacher" ? <p>此功能验证入口目前仅提供教师课堂管理；当前账号没有教师权限。</p> : <>
        <h2>授权课堂</h2>
        <button disabled={busy} onClick={() => openForm(null)}>创建课堂</button>
        <button disabled={busy} onClick={() => void perform(async () => {
          setClassrooms(await api.classrooms()); setNotice("课堂列表已重新读取。");
        })}>重新读取列表</button>
        {classrooms.length === 0 ? <p>当前账号没有课堂。</p> : <div className="table-scroll"><table>
          <thead><tr><th>课堂</th><th>日期</th><th>版本</th><th>操作</th></tr></thead>
          <tbody>{classrooms.map((classroom) => <tr key={classroom.id}>
            <td>{classroom.title}</td><td>{classroom.date}</td><td>{classroom.revision}</td>
            <td><button disabled={busy} onClick={() => void perform(async () => {
              setSelected(await api.classroom(classroom.id)); setFormOpen(false);
            })}>打开</button></td>
          </tr>)}</tbody>
        </table></div>}
        {formOpen ? <ClassroomForm key={formKey} classroom={selected} busy={busy} onSave={save}
          onCancel={() => setFormOpen(false)} /> : selected && <section aria-label="课堂详情">
          <h2>{selected.title}</h2>
          <p>课堂标识：{selected.id}；教师：{selected.teacher_id}；版本：{selected.revision}</p>
          <p>教学目标：{selected.objective}</p><p>名单：{selected.students.join("、")}</p>
          <p>材料来源：{selected.source}</p><p>使用授权：{selected.authorization}</p>
          {selected.questions.map((question) => <article key={question.id}>
            <h3>{question.id}</h3><p>{question.text}</p><p>参考答案：{question.reference_answer}</p>
            <p>图形说明：{question.diagram_description ?? "未提供"}</p>
            <QuestionDiagram question={question} />
            {question.diagram_required && !question.diagram_description && <p>需要补充图形，当前不能据此分析。</p>}
          </article>)}
          <button disabled={busy} onClick={() => openForm(selected)}>修改课堂</button>
          <ManualExercises key={`manual/${user.id}/${selected.id}`} classroomId={selected.id} />
          <SpeechPanel key={`speech/${user.id}/${selected.id}`} classroom={selected} />
          <StudentFeedbackQueue key={`feedback/${user.id}/${selected.id}`} classroomId={selected.id} />
        </section>}
      </>}
    </>}
  </main>;
}
