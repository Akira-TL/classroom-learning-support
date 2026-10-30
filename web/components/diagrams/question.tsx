import { useId } from "react";
import { diagramFor } from "../../lib/diagrams/templates";
import type { Question } from "../../lib/types";

export function QuestionDiagram({ question }: { question: Question }) {
  const uniqueId = useId();
  if (!question.diagram_required) return null;
  const template = diagramFor(question);
  if (!template) return <p>当前说明没有对应的固定图形示意；未将自定义文字猜测成原图。</p>;
  const total = template.widths.reduce<number>((sum, width) => sum + width, 0);
  const parts = template.widths.map((width, index) => {
    const preceding = template.widths.slice(0, index).reduce<number>((sum, value) => sum + value, 0);
    return { x: 20 + preceding / total * 600, width: width / total * 600, label: ["甲", "乙", "丙", "丁"][index] };
  });
  return <figure>
    <svg viewBox="0 0 640 160" width="640" style={{ maxWidth: "100%", height: "auto" }}
      role="img" aria-labelledby={`${uniqueId}-title ${uniqueId}-description`}>
      <title id={`${uniqueId}-title`}>{question.id}：长方形四块示意</title>
      <desc id={`${uniqueId}-description`}>{template.accessibleDescription}
        按教师核验说明绘制的示意，非原始课堂图片。
      </desc>
      <rect x="20" y="25" width="600" height="100" fill="white" stroke="black" strokeWidth="2" />
      {parts.map((part, index) => <g key={part.label}>
        {index > 0 && <line x1={part.x} x2={part.x} y1="25" y2="125" stroke="black" strokeWidth="2" />}
        <text x={part.x + part.width / 2} y="82" textAnchor="middle" fill="black" fontSize="20">
          {part.label}
        </text>
      </g>)}
    </svg>
    <figcaption>按教师核验说明绘制的示意，非原始课堂图片。</figcaption>
  </figure>;
}
