import assert from "node:assert/strict";
import test from "node:test";
import { ExportRequests, mergeExportList, preferExport } from "./coordination.ts";
import type { VersionedExport } from "./coordination.ts";

test("迟到有效列表不能取代撤回后的当前结果", () => {
  const requests = new ExportRequests();
  const refresh = requests.begin("class-a/plan-1/v1");
  const revoke = requests.begin("class-a/plan-1/v1");
  assert.equal(requests.current(revoke, "class-a/plan-1/v1"), true);
  assert.equal(requests.current(refresh, "class-a/plan-1/v1"), false);
  const revoked: VersionedExport = { id: "r1", revision: 2, status: "revoked" as const };
  const delayed: VersionedExport = { id: "r1", revision: 1, status: "active" as const };
  assert.deepEqual(mergeExportList([revoked], [delayed]), [revoked]);
});

test("终止状态不能被更大或相同版本active恢复", () => {
  const old: VersionedExport = { id: "r1", revision: 2, status: "stale" as const };
  assert.deepEqual(preferExport(old, { id: "r1", revision: 2, status: "active" }), old);
  assert.deepEqual(preferExport(old, { id: "r1", revision: 9, status: "active" }), old);
  assert.deepEqual(preferExport(old, { id: "r1", revision: 3, status: "deleted" }), {
    id: "r1", revision: 3, status: "deleted",
  });
});

test("切换课堂或版本后旧请求完成也不可信", () => {
  const requests = new ExportRequests();
  const old = requests.begin("class-a/plan-1/v1");
  const fresh = requests.begin("class-b/plan-2/v2");
  assert.equal(requests.current(old, "class-b/plan-2/v2"), false);
  requests.finish(old);
  assert.equal(requests.count(), 1);
  assert.equal(requests.current(fresh, "class-b/plan-2/v2"), true);
  requests.cancel();
  assert.equal(requests.current(fresh, "class-b/plan-2/v2"), false);
});

test("单个请求结束不能把其他在途请求误标空闲", () => {
  const requests = new ExportRequests();
  const first = requests.begin("class-a/plan-1/v1");
  const second = requests.begin("class-a/plan-1/v1");
  assert.equal(requests.count(), 2);
  requests.finish(second);
  assert.equal(requests.count(), 1);
  requests.finish(first);
  assert.equal(requests.count(), 0);
});

