"use client";

import { useState } from "react";
import type { FormEvent } from "react";

export function LoginForm({ busy, onLogin }: {
  busy: boolean; onLogin: (username: string, password: string) => Promise<void>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try { await onLogin(username, password); } finally { setPassword(""); }
  }

  return <form onSubmit={submit} className="surface-card login-card">
    <fieldset disabled={busy}>
      <legend>登录演示账号</legend>
      <h2>欢迎回来</h2>
      <p className="muted">输入演示账号，继续教学与学习反馈。</p>
      <label>账号<input required autoComplete="username" value={username}
        onChange={(event) => setUsername(event.target.value)} /></label>
      <label>密码<input required type="password" autoComplete="current-password" value={password}
        onChange={(event) => setPassword(event.target.value)} /></label>
      <button type="submit">{busy ? "正在登录…" : "登录"}</button>
      <details><summary>演示账号说明</summary>
        <p>教师 teacher-01／teacher-02；学生 student-01 至 student-10；家长 parent-01；管理者 admin-01。</p>
        <p>密码使用本机配置。家长绑定学生 student-01，账号角色由服务端校验。</p>
      </details>
    </fieldset>
  </form>;
}
