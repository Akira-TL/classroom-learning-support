"use client";

import { useEffect, useRef, useState } from "react";
import { LoginForm } from "../components/login-form";
import { TeacherHome } from "../components/classrooms/teacher-home";
import { Shell } from "../components/chrome/shell";
import { AppIcon } from "../components/chrome/icons";
import { StudentReader } from "../components/students/reader";
import { ParentReader } from "../components/reports/parent-reader";
import { AdminOverview } from "../components/overview/panel";
import { selectionAfterRemoval } from "../lib/deletion/attempts";
import { ApiError, api } from "../lib/api";
import type { Classroom, ClassroomContent, User } from "../lib/types";

export default function Home() {
  const [view, setView] = useState("classrooms");
  const [user, setUser] = useState<User | null>(null);
  const authScope = useRef({ userId: user?.id ?? null, generation: 0 });
  if (authScope.current.userId !== (user?.id ?? null)) {
    authScope.current = { userId: user?.id ?? null, generation: authScope.current.generation + 1 };
  }
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [{ selected, formOpen }, setSelection] = useState<{ selected: Classroom | null; formOpen: boolean }>({
    selected: null, formOpen: false,
  });
  const setSelected = (value: Classroom | null) => setSelection((previous) => ({ ...previous, selected: value }));
  const setFormOpen = (value: boolean) => setSelection((previous) => ({ ...previous, formOpen: value }));
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
      setSelected(saved); setFormOpen(false); setView("review");
      setClassrooms(await api.classrooms());
      setNotice(`课堂已保存，版本 ${saved.revision}。`);
    });
  }

  function openForm(classroom: Classroom | null) {
    setSelected(classroom); setFormOpen(true); setView("classrooms"); setFormKey((value) => value + 1);
  }

  async function removed(deletedClassroomId: string) {
    const generation = authScope.current.generation;
    setSelection((previous) => selectionAfterRemoval(previous, deletedClassroomId));
    const updated = await api.classrooms();
    if (authScope.current.generation !== generation) return;
    setClassrooms(updated);
    setNotice("课堂已移除，受控入口已关闭；清除任务结果请在删除区域查看。");
  }

  return <Shell user={user} activeView={user?.role === "teacher" ? view : user?.role ?? "classrooms"}
    onNavigate={setView} actions={user && <>
      {user.role === "teacher" && selected && <>
        <span className="badge badge-warning">真实语音服务尚待联调</span>
        <button disabled={busy} onClick={() => openForm(selected)}>修改课堂</button>
      </>}
      <button disabled={busy} className="header-session" onClick={() => void perform(async () => {
        const current = await api.me(); setUser(current); setNotice("当前会话有效。");
      })}>检查当前会话</button>
      <button disabled={busy} onClick={() => void perform(async () => {
        await api.logout(); setUser(null); setClassrooms([]); setSelected(null); setFormOpen(false);
        setView("classrooms"); setNotice("已退出登录。");
      })}><AppIcon name="signOut" size={17} />退出登录</button>
    </>}>
    {error && <p role="alert">{error}</p>}
    <p className="app-status" role="status" aria-live="polite">{busy ? "正在处理，请稍候…" : notice}</p>
    {!user ? <div className="login-layout"><div className="login-intro">
      <span className="badge badge-blue">有依据的教学支持</span><h1>从一句课堂表达，<br />接续下一次学习。</h1>
      <p>核对原话，确认学习证据，再形成练习与教学安排。</p>
      <p className="muted">当前使用成人模拟资料进行演示，真实语音服务尚待联调。</p>
    </div><LoginForm busy={busy} onLogin={login} /></div>
      : user.role === "student" ? <StudentReader key={user.id} />
        : user.role === "parent" ? <ParentReader key={user.id} />
          : user.role === "admin" ? <AdminOverview key={user.id} />
            : <TeacherHome key={user.id} view={view} onView={setView} classrooms={classrooms}
              selected={selected} formOpen={formOpen} formKey={formKey} busy={busy}
              onForm={openForm} onSave={save} onCancel={() => setFormOpen(false)} onRemoved={removed}
              onRefresh={() => perform(async () => {
                setClassrooms(await api.classrooms()); setNotice("课堂列表已重新读取。");
              })} onOpen={(id) => perform(async () => {
                setSelected(await api.classroom(id)); setFormOpen(false); setView("review");
              })} />}
  </Shell>;
}
