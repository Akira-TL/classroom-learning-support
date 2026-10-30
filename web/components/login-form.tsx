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

  return <form onSubmit={submit}>
    <fieldset disabled={busy}>
      <legend>登录演示账号</legend>
      <p>教师账号为 teacher-01 或 teacher-02；密码由本机配置，不在页面预填。</p>
      <label>账号<input required autoComplete="username" value={username}
        onChange={(event) => setUsername(event.target.value)} /></label>
      <label>密码<input required type="password" autoComplete="current-password" value={password}
        onChange={(event) => setPassword(event.target.value)} /></label>
      <button type="submit">{busy ? "正在登录…" : "登录"}</button>
    </fieldset>
  </form>;
}
