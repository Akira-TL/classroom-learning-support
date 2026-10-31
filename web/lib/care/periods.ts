export function weekPeriods(today: string) {
  const date = new Date(`${today}T00:00:00Z`);
  const monday = new Date(date);
  monday.setUTCDate(date.getUTCDate() - (date.getUTCDay() + 6) % 7);
  const shift = (days: number) => {
    const shifted = new Date(monday); shifted.setUTCDate(monday.getUTCDate() + days);
    return shifted.toISOString().slice(0, 10);
  };
  return { baseline_start: shift(-7), baseline_end: shift(-1), current_start: shift(0), current_end: shift(6) };
}
import type { CompareRequest } from "./types";

export function sameComparisonScope(left: CompareRequest, right: CompareRequest) {
  return left.student_id === right.student_id && left.baseline_start === right.baseline_start
    && left.baseline_end === right.baseline_end && left.current_start === right.current_start
    && left.current_end === right.current_end;
}

