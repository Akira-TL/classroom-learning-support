import { useId } from "react";
import { diagramFor } from "../../lib/diagrams/templates";
import type { Question } from "../../lib/types";
import styles from "./question.module.css";

const fills = ["#cce3fb", "#d9f0e3", "#ffecd1", "#e5dff9"];

export function QuestionDiagram({ question }: { question: Question }) {
  const uniqueId = useId();
  if (!question.diagram_required) return null;
  const template = diagramFor(question);
  if (!template) return <p>当前说明没有对应的固定图形示意；未将自定义文字猜测成原图。</p>;
  const total = template.widths.reduce<number>((sum, width) => sum + width, 0);
  const parts = template.widths.map((width, index) => {
    const preceding = template.widths.slice(0, index).reduce<number>((sum, value) => sum + value, 0);
    return { x: 8 + preceding / total * 304, width: width / total * 304, label: ["甲", "乙", "丙", "丁"][index] };
  });
  return <figure className={styles.figure}>
    <svg className={styles.graphic} viewBox="0 0 320 144" width="320" height="144"
      role="img" aria-labelledby={`${uniqueId}-title ${uniqueId}-description`}>
      <title id={`${uniqueId}-title`}>{question.id}：长方形四块示意</title>
      <desc id={`${uniqueId}-description`}>{template.accessibleDescription}
        按教师核验说明绘制的示意，非原始课堂图片。
      </desc>
      {parts.map((part, index) => <g key={part.label}>
        <rect x={part.x} y="8" width={part.width} height="128" fill={fills[index]} />
        {index > 0 && <line x1={part.x} x2={part.x} y1="8" y2="136" stroke="#31445a" strokeWidth="1.5" />}
        <text x={part.x + part.width / 2} y="72" textAnchor="middle" dominantBaseline="central"
          fill="#17243a" fontSize="22" fontWeight="600">
          {part.label}
        </text>
      </g>)}
      <rect x="8" y="8" width="304" height="128" fill="none" stroke="#31445a" strokeWidth="1.5" />
    </svg>
    <figcaption className={styles.caption}>
      <span className={styles.ratio}>面积比 {template.widths.join(":")}（示意）</span>
      <span>按教师核验说明绘制，非原始课堂图片。</span>
    </figcaption>
  </figure>;
}
