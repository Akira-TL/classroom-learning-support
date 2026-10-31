import type { AutoExplanation, RecipientExplanation } from "../../../lib/care/labels/types";
import styles from "./labels.module.css";

export function AutomaticReport({ result }: { result: AutoExplanation | RecipientExplanation }) {
  return <article className={styles.report} aria-label="自动解释与统计报告">
    <h2>自动解释与统计报告</h2><p>{result.content.summary}</p>
    <h3>变化说明</h3><p>{result.content.change_explanation}</p>
    <h3>需要了解与核实</h3><ul>{result.content.followup_questions.map((question, index) => <li key={index}>
      {question}</li>)}</ul><h3>后续建议</h3><p>{result.content.followup}</p>
    <small className={styles.muted}>基于所提供资料自动生成 · 模型 {result.model}</small>
  </article>;
}
