"use client";

import { useState } from "react";
import type { DemoRole } from "../lib/types";
import { AppIcon } from "./chrome/icons";
import { demoRoleNames } from "./chrome/roles";
import styles from "./chrome/login.module.css";

const entries = [
  { role: "teacher", icon: "teaching", description: "进入课堂，查看原声、标签变化与教学反馈" },
  { role: "head_teacher", icon: "classrooms", description: "查看学生历史信息与班级跟进建议" },
  { role: "parent", icon: "parent", description: "查看固定绑定学生 student-01 的个人反馈" },
  { role: "teaching_director", icon: "admin", description: "查看授权教学汇总与统计" },
] as const;

export function LoginForm({ busy, onLogin }: {
  busy: boolean; onLogin: (role: DemoRole, studentId?: string) => Promise<void>;
}) {
  const [student, setStudent] = useState("student-01");
  return <section className={styles.card} aria-label="选择演示角色">
    <span className={styles.badge}>演示环境</span><h2>选择角色，直接进入</h2>
    <p className={styles.intro}>选择你希望查看的身份，无需输入账号和密码。</p>
    <div className={styles.roles}>
      {entries.map((entry) => <button type="button" key={entry.role} disabled={busy}
        onClick={() => void onLogin(entry.role)}>
        <AppIcon name={entry.icon} size={25} /><strong>{demoRoleNames[entry.role]}</strong>
        <span>{entry.description}</span>
      </button>)}
      <article className={styles.student}><div><h3>学生</h3><p>选择一位固定演示学生，查看其个人报告。</p></div>
        <div><label>演示学生<select value={student} disabled={busy} onChange={(event) => setStudent(event.target.value)}>
          {Array.from({ length: 10 }, (_, index) => `student-${String(index + 1).padStart(2, "0")}`)
            .map((id) => <option key={id} value={id}>{id}</option>)}
        </select></label><button type="button" disabled={busy} onClick={() => void onLogin("student", student)}>
          进入学生视角</button></div>
      </article>
    </div>
    <p className={styles.note}>{busy ? "正在进入，请稍候…" : "退出当前角色后，可重新选择其他视角。"}</p>
  </section>;
}
