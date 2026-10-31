import assert from "node:assert/strict";
import test from "node:test";
import { sameComparisonScope, weekPeriods } from "./periods.ts";

test("周日和跨月日期均按周一至周日比较上周与本周", () => {
  assert.deepEqual(weekPeriods("2026-11-01"), {
    baseline_start: "2026-10-19", baseline_end: "2026-10-25",
    current_start: "2026-10-26", current_end: "2026-11-01",
  });
  assert.deepEqual(weekPeriods("2026-11-02"), {
    baseline_start: "2026-10-26", baseline_end: "2026-11-01",
    current_start: "2026-11-02", current_end: "2026-11-08",
  });
});

test("切换学生或任一期日期后旧比较不得继续成为反馈依据", () => {
  const scope = { student_id: "student-01", ...weekPeriods("2026-10-31") };
  assert.equal(sameComparisonScope(scope, { ...scope }), true);
  assert.equal(sameComparisonScope(scope, { ...scope, student_id: "student-02" }), false);
  assert.equal(sameComparisonScope(scope, { ...scope, baseline_start: "2026-10-18" }), false);
  assert.equal(sameComparisonScope(scope, { ...scope, current_end: "2026-11-02" }), false);
});
