"use client";

import { useEffect, useState } from "react";
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
  const [mobilePane, setMobilePane] = useState<"layout" | "student">("layout");
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 1000px)");
    const update = () => setNarrow(query.matches);
    update(); query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return <section className={common.page} aria-label="课堂详情"><header className={common.heading}>
    <h1>课堂详情</h1><p>{classroom.title}</p>
  </header>
  <nav className={styles.mobilePanes} aria-label="课堂详情区域">
    <button type="button" aria-pressed={mobilePane === "layout"} onClick={() => setMobilePane("layout")}>教室布局</button>
    <button type="button" aria-pressed={mobilePane === "student"} onClick={() => setMobilePane("student")}>
      {selected ? `学生${Number(selected.replace("student-", ""))}信息` : "学生信息"}</button>
  </nav>
  <div className={styles.windows}><section className={`${common.card} ${styles.seatPanel}`}
    data-mobile-active={mobilePane === "layout"} aria-label="演示教室座位布局">
    <h2>教室布局</h2>
    <div className={styles.blackboard}>讲台</div>
    <div className={styles.seats}>{seats(classroom.students).map((seat) => <button key={seat.position} type="button"
      disabled={!seat.student} aria-pressed={selected === seat.student}
      aria-label={`${seat.student ?? "空位"}，${seat.position}号座位`}
      onClick={() => { if (seat.student) { setSelected(seat.student); setMobilePane("student"); } }}>
      <span>{seat.student ? `学生${seat.student.replace(/^student-/, "")}` : "空位"}</span>
      <small>{seat.position}号座位</small>
    </button>)}</div>
  </section>
  <div className={styles.studentWindow} data-mobile-active={mobilePane === "student"} aria-label="学生信息面板">
  {!selected && <section className={common.card}><h2>信息面板</h2><p>选择左侧学生，查看其上周与本周记录。</p></section>}
  {classroom.students.map((student) => <div className={styles.studentPanel} key={student} hidden={student !== selected}>
    <LabelDashboard classroom={classroom} student={student}
      active={active && student === selected && (!narrow || mobilePane === "student")}
      initialPerspective={initialPerspective} />
  </div>)}</div></div></section>;
}
