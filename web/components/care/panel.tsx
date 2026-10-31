"use client";

import { useState } from "react";
import type { Classroom } from "../../lib/types";
import { seats } from "../../lib/care/labels/presentation";
import type { Perspective } from "../../lib/care/labels/types";
import { LabelDashboard } from "./labels/dashboard";
import common from "./care.module.css";
import styles from "./labels/labels.module.css";

export function CarePanel({ classroom, active = true, initialPerspective = "teacher" }: {
  classroom: Classroom; active?: boolean; initialPerspective?: Perspective;
}) {
  const [selected, setSelected] = useState("");
  return <section className={common.page} aria-label="课堂详情"><header className={common.heading}>
    <h1>课堂详情</h1><p>{classroom.title} · 点击左侧学生，在右侧查看历史标签、时间分布与对应原声。</p>
  </header><div className={styles.windows}><section className={common.card} aria-label="演示教室座位布局">
    <h2>教室布局</h2><p className={common.muted}>演示座位布局，可随数据调整；按名单排布，不代表真实座位或语音定位。</p>
    <div className={styles.blackboard}>讲台方向（示意）</div>
    <div className={styles.seats}>{seats(classroom.students).map((seat) => <button key={seat.position} type="button"
      disabled={!seat.student} aria-pressed={selected === seat.student}
      aria-label={`${seat.student ?? "空位"}，${seat.position}号座位`}
      onClick={() => seat.student && setSelected(seat.student)}>
      <span>{seat.student ? `学生${seat.student.replace(/^student-/, "")}` : "空位"}</span>
      <small>{seat.position}号座位</small>
    </button>)}</div>
  </section>
  <div aria-label="学生信息面板">
  {!selected && <section className={common.card}><h2>信息面板</h2><p>选择左侧学生，查看其上周与本周记录。</p></section>}
  {classroom.students.map((student) => <div key={student} hidden={student !== selected}>
    <LabelDashboard classroom={classroom} student={student} active={active && student === selected}
      initialPerspective={initialPerspective} />
  </div>)}</div></div></section>;
}
