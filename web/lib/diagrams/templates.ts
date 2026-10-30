import type { Question } from "../types";

export const diagramTemplates = [
  {
    id: "unequal", label: "不等分长方形（四块）",
    description: "四块面积分别占整体的二分之一、四分之一、八分之一、八分之一。",
    widths: [4, 2, 1, 1],
    accessibleDescription: "一个长方形分成四块，大小不同，从左至右依次标为甲、乙、丙、丁。",
  },
  {
    id: "equal", label: "等分长方形（四块）",
    description: "四块面积分别占整体的四分之一、四分之一、四分之一、四分之一。",
    widths: [1, 1, 1, 1],
    accessibleDescription: "一个长方形分成四块，大小相同，从左至右依次标为甲、乙、丙、丁。",
  },
] as const;

export function diagramFor(question: Question) {
  return question.diagram_required
    ? diagramTemplates.find((template) => template.description === question.diagram_description)
    : undefined;
}
