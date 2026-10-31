export function countLabel(value: number | null) { return value === null ? "暂无数据" : `${value} 次`; }
export function minuteRate(perHour: number | null) {
  return perHour === null ? "采集时长缺失，不计算频率" : `${(perHour / 60).toFixed(2)} 次/分钟`;
}
export function seats(students: string[], columns = 4) {
  const length = Math.max(columns * 3, Math.ceil(students.length / columns) * columns);
  return Array.from({ length }, (_, index) => ({ position: index + 1, student: students[index] ?? null }));
}
