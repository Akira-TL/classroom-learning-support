"use client";

import type { Classroom, ClassroomContent, DemoRole } from "../../lib/types";
import { ClassroomForm } from "../classroom-form";
import { AppIcon } from "../chrome/icons";
import { SpeechPanel } from "../speech-panel";
import { InputPanel } from "../inputs/panel";
import { ManualExercises } from "../manual-exercises/panel";
import { StudentFeedbackQueue } from "../students/feedback-queue";
import { DeletionPanel } from "../deletion/panel";
import { CarePanel } from "../care/panel";
import "./teacher-home.css";

interface Props {
  displayRole?: DemoRole;
  view: string; onView: (view: string) => void; classrooms: Classroom[];
  selected: Classroom | null; formOpen: boolean; formKey: number; busy: boolean;
  onOpen: (id: string) => Promise<void>; onForm: (classroom: Classroom | null) => void;
  onSave: (content: ClassroomContent, key: string) => Promise<void>;
  onCancel: () => void; onRefresh: () => Promise<void>; onRemoved: (id: string) => Promise<void>;
}

export function TeacherHome(props: Props) {
  const { view, selected, busy } = props;
  const workspaceView = view === "teaching" || view === "publishing" ? view : "review";
  return <div className={`teacher-pages teacher-view-${view}`}>
    <section hidden={view !== "classrooms"} aria-label="课堂管理" className="classroom-catalog">
      <header className="catalog-heading"><div><p className="eyebrow">教学准备</p><h1>我的课堂</h1>
        <p>从具体的题目与课堂表达出发，保留每一次教师核验。</p></div>
        <div className="action-row">
          <button disabled={busy} onClick={() => void props.onRefresh()}><AppIcon name="refresh" />刷新列表</button>
          <button className="button-primary" disabled={busy} onClick={() => props.onForm(null)}>
            <AppIcon name="plus" />创建课堂</button>
        </div></header>
      {props.classrooms.length === 0 && <div className="empty-state"><h2>准备第一堂课</h2>
        <p>添加教学目标、题目和授权材料，开始核验课堂表达。</p></div>}
      <div className="classroom-cards">{props.classrooms.map((item) => <article className="surface-card" key={item.id}>
        <div className="catalog-card-top"><span className="badge badge-blue">课堂资料</span><time>{item.date}</time></div>
        <h2>{item.title}</h2><p>{item.objective}</p><p className="muted">{item.students.length} 位虚构学生 ·
          {item.questions.length} 道题目</p>
        <button className="button-primary" disabled={busy} onClick={() => void props.onOpen(item.id)}>
          进入核验工作台<AppIcon name="next" size={17} /></button>
        <button disabled={busy} onClick={() => props.onForm(item)}>修改课堂</button>
      </article>)}</div>
      {props.formOpen && <div className="surface-card classroom-editor"><ClassroomForm key={props.formKey}
        classroom={selected} busy={busy} onSave={props.onSave} onCancel={props.onCancel} /></div>}
      {selected && <details className="surface-card classroom-tools"><summary>音频输入与归档 · {selected.title}</summary>
        <p>文件和麦克风会送往本机语音服务；设备与重叠分离效果仍需实测。离开课堂管理会停止本机输入。</p>
        {view === "classrooms" && <InputPanel key={selected.id} classroomId={selected.id} />}
      </details>}
    </section>
    <section hidden={view !== "care"} aria-label="课堂详情工作区">
      {selected ? <CarePanel key={selected.id} classroom={selected} active={view === "care"}
        initialPerspective={props.displayRole === "head_teacher" ? "head_teacher" : "teacher"} />
        : <div className="empty-state"><h1>先选择一堂课</h1><p>选择课堂名单，查看学生观察与跟进。</p>
          <button onClick={() => props.onView("classrooms")}>返回课堂库</button></div>}
    </section>
    <section hidden={view === "classrooms" || view === "care"} aria-label="教师工作区">
      {selected ? <>
        <h1 className="sr-only">{selected.title}</h1>
        <SpeechPanel key={selected.id} classroom={selected} view={workspaceView}
          active={view !== "classrooms" && view !== "care"} onViewChange={props.onView} />
        <details className="workspace-utilities"><summary>课堂工具与资料</summary>
        <div hidden={view !== "teaching"}>
          <details className="surface-card classroom-tools"><summary>人工通用练习 · 无需个人学习证据</summary>
            <ManualExercises key={selected.id} classroomId={selected.id} /></details>
        </div>
        <div hidden={view !== "publishing"}>
          <StudentFeedbackQueue key={selected.id} classroomId={selected.id} />
        </div>
        <details className="surface-card classroom-tools"><summary>课堂资料与授权记录</summary>
          <p>教学目标：{selected.objective}</p><p>材料来源：{selected.source}</p>
          <p>使用授权：{selected.authorization}</p><p>名单：{selected.students.join("、")}</p>
          <p>课堂标识：{selected.id} · 版本 {selected.revision}</p></details>
        </details>
      </> : <div className="empty-state"><h1>先选择一堂课</h1>
        <p>核验、教学支持和发布反馈都与具体课堂关联。</p>
        <button className="button-primary" onClick={() => props.onView("classrooms")}>查看我的课堂</button></div>}
    </section>
    <details hidden={view !== "classrooms" && view !== "publishing"} className="classroom-maintenance">
      <summary>课堂资源清理</summary>
      <DeletionPanel classroom={selected} onRemoved={props.onRemoved} />
    </details>
  </div>;
}
