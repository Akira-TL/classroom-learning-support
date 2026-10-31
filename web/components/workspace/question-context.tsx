"use client";

import { useEffect, useState } from "react";
import type { Classroom } from "../../lib/types";
import type { Utterance } from "../../lib/speech";
import { QuestionDiagram } from "../diagrams/question";
import styles from "./workspace.module.css";

export function QuestionContext({ classroom, utterance }: { classroom: Classroom; utterance?: Utterance }) {
  const [questionId, setQuestionId] = useState(utterance?.question_id ?? classroom.questions[0]?.id ?? "");
  useEffect(() => {
    setQuestionId(utterance?.question_id ?? classroom.questions[0]?.id ?? "");
  }, [utterance?.session_id, utterance?.segment_id, utterance?.question_id, classroom.id]);
  const question = classroom.questions.find((item) => item.id === questionId);
  return <aside className={styles.card} aria-label="题目与教学背景">
    <span className={styles.eyebrow}>题目背景</span>
    <h2>{classroom.title}</h2>
    <p className={styles.muted}>{classroom.date} · {classroom.students.length} 名演示学生</p>
    <label>查看题目<select value={questionId} onChange={(event) => setQuestionId(event.target.value)}>
      {classroom.questions.map((item, index) => <option key={item.id} value={item.id}>
        题目 {index + 1} · {item.id}
      </option>)}
    </select></label>
    {question && <>
      <h3>{question.text}</h3>
      <div className={styles.diagram}><QuestionDiagram question={question} /></div>
      {question.diagram_required && <details><summary>图形文字说明</summary>
        <p>{question.diagram_description ?? "尚未提供图形说明，请先补齐材料。"}</p>
      </details>}
      <details><summary>教师参考答案</summary><p>{question.reference_answer}</p></details>
    </>}
    <div className={styles.contextBlock}><h4>本课目标</h4><p>{classroom.objective}</p></div>
    <details className={styles.contextBlock}><summary>材料来源与授权</summary>
      <p>{classroom.source}</p><p>{classroom.authorization}</p>
    </details>
    <p className={styles.muted}>这里切换题目仅用于阅读；发言归属须在右侧单独核验。</p>
  </aside>;
}
