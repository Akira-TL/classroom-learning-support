"use client";

import type { ReactNode } from "react";
import type { User } from "../../lib/types";
import { AppIcon, type AppIconName } from "./icons";
import "./shell.css";

interface NavigationItem {
  view: string;
  label: string;
  icon: AppIconName;
}

const teacherNavigation: NavigationItem[] = [
  { view: "classrooms", label: "课堂", icon: "classrooms" },
  { view: "review", label: "核验工作台", icon: "review" },
  { view: "teaching", label: "教学支持", icon: "teaching" },
  { view: "publishing", label: "发布反馈", icon: "publishing" },
];

const roleNavigation: Record<Exclude<User["role"], "teacher">, NavigationItem> = {
  student: { view: "student", label: "我的学习反馈", icon: "student" },
  parent: { view: "parent", label: "孩子的学习反馈", icon: "parent" },
  admin: { view: "admin", label: "教学支持汇总", icon: "admin" },
};

const roleLabels: Record<User["role"], string> = {
  teacher: "教师", student: "学生", parent: "家长", admin: "管理者",
};

export interface ShellProps {
  user: User | null;
  activeView: string;
  onNavigate: (view: string) => void;
  children: ReactNode;
  actions?: ReactNode;
}

export function Shell({ user, activeView, onNavigate, children, actions }: ShellProps) {
  const navigation = user
    ? user.role === "teacher" ? teacherNavigation : [roleNavigation[user.role]]
    : [];

  return (
    <div className={`shell-grid${user ? "" : " shell-signed-out"}`}>
      <a className="skip-link" href="#app-main-content">跳转到主要内容</a>
      <header className="app-header">
        <div className="app-brand">
          <span className="brand-mark"><AppIcon name="teaching" size={22} /></span>
          <span>课堂学习支持</span>
        </div>
        <div className="header-context">
          <span className="environment-badge">演示环境</span>
          {user && <span className="header-user" title={user.id}>
            <AppIcon name="user" size={18} />{roleLabels[user.role]}
          </span>}
          {actions && <div className="header-actions">{actions}</div>}
        </div>
      </header>
      {user && <aside className="app-rail">
        <nav className="rail-navigation" aria-label="主要功能">
          {navigation.map((item) => <button
            key={item.view}
            type="button"
            className={`rail-item${activeView === item.view ? " is-active" : ""}`}
            aria-current={activeView === item.view ? "page" : undefined}
            onClick={() => onNavigate(item.view)}
          >
            <AppIcon name={item.icon} /><span>{item.label}</span>
          </button>)}
        </nav>
        <p className="rail-note">教师核验后发布</p>
      </aside>}
      <main id="app-main-content" className="app-content" tabIndex={-1}>{children}</main>
    </div>
  );
}
