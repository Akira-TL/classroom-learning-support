import assert from "node:assert/strict";
import test from "node:test";
import { ParentReportRequests, mergeParentReports, preferParentReport } from "./coordination.ts";
import type { ParentReport } from "../../lib/reports.ts";

function report(status: ParentReport["status"], revision: number): ParentReport {
  return { id: "report-01", classroom_id: "class-A", student_id: "student-01", status, revision,
    published_at: "2026-10-31T00:00:00Z", summary: status === "published" ? "摘要" : null,
    home_activity: status === "published" ? "活动" : null, evidence_id: "evidence-A", evidence_revision: 1 };
}
test("撤回开始即拦截旧published列表，操作结果后的新核实仍可接收", () => {
  const requests = new ParentReportRequests(); requests.setSource("A");
  const oldList = requests.beginList("A"); assert.ok(oldList);
  const revoke = requests.beginOperation("A", true); assert.ok(revoke);
  assert.equal(requests.current(oldList), false);
  assert.equal(requests.current(revoke), true);
  const newList = requests.beginList("A"); assert.ok(newList);
  assert.equal(requests.current(newList), true);
  assert.equal(requests.current(revoke), true);
  assert.equal(requests.finish(revoke), true);
});
test("A预览或发布在切B后返回不能写回，迟到finally不能解除B操作锁", () => {
  for (const mutation of [false, true]) {
    const requests = new ParentReportRequests(); requests.setSource("A");
    const oldOperation = requests.beginOperation("A", mutation); assert.ok(oldOperation);
    requests.setSource("B");
    const newOperation = requests.beginOperation("B", true); assert.ok(newOperation);
    assert.equal(requests.current(oldOperation), false);
    assert.equal(requests.finish(oldOperation), false);
    assert.equal(requests.current(newOperation), true);
    assert.equal(requests.beginOperation("B", true), null);
    assert.equal(requests.beginList("A"), null);
  }
});
test("A到B再回A或卸载不会复活原请求，新列表不会被旧列表抢回", () => {
  const requests = new ParentReportRequests(); requests.setSource("A");
  const first = requests.beginList("A"); assert.ok(first);
  requests.setSource("B"); requests.setSource("A");
  assert.equal(requests.current(first), false);
  const second = requests.beginList("A"); assert.ok(second);
  const third = requests.beginList("A"); assert.ok(third);
  assert.equal(requests.current(second), false); assert.equal(requests.current(third), true);
  requests.cancel(); assert.equal(requests.current(third), false);
});
test("撤回或失效版本不能被旧published列表恢复，保留停止提供正文状态", () => {
  for (const status of ["revoked", "stale"] as const) {
    const stopped = report(status, 2);
    for (const revision of [1, 2, 3]) {
      assert.equal(preferParentReport(stopped, report("published", revision)), stopped);
      const [merged] = mergeParentReports([stopped], [report("published", revision)]);
      assert.equal(merged, stopped); assert.equal(merged.summary, null);
    }
  }
});
test("合法新版本可更新，其它报告按自身id合并，不混来源或版本", () => {
  const published = report("published", 1); const revoked = report("revoked", 2);
  assert.equal(preferParentReport(published, revoked), revoked);
  assert.equal(preferParentReport(revoked, report("stale", 1)), revoked);
  const other = { ...published, id: "report-02" };
  assert.deepEqual(mergeParentReports([revoked], [published, other]), [revoked, other]);
});
