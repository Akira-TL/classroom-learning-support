import assert from "node:assert/strict";
import { test } from "node:test";
import type { Classroom } from "../types.ts";
import type { DeletionView } from "./api.ts";
import { createAttempt, rememberAttempt, rememberTask, selectionAfterRemoval } from "./attempts.ts";
import type { DeletionAttempt } from "./attempts.ts";

function classroom(id: string): Classroom {
  return {
    id, teacher_id: "teacher-01", revision: 4, title: `课堂${id}`, date: "2026-10-31",
    objective: "核对平均分条件", students: ["student-01"], source: "synthetic",
    authorization: "成人模拟教学材料，仅用于测试",
    questions: [{
      id: "q-1", text: "平均分成四份，每份占整体多少？", reference_answer: "四分之一",
      diagram_required: false, diagram_description: null,
    }],
  };
}

function task(id: string, cid: string, revision: number): DeletionView {
  return {
    id, classroom_id: cid, revision, created_at: "2026-10-31T00:00:00Z",
    local_status: "complete", local_complete: true, remaining_files: 0,
    external_status: "not_requested", external_pending: true, error: null,
    notice: "本机清理完成，供应方删除未请求。",
  };
}

test("A结果未知后发起B，仍保留A的原课堂、原确认版本和同一幂等键", () => {
  const a: DeletionAttempt = {
    ...createAttempt("A", "课堂甲", 4, "request-key-for-A"),
    state: "unknown", operation: 1, error: "响应丢失，不能确定是否执行",
  };
  const b = { ...createAttempt("B", "课堂乙", 7, "request-key-for-B"), operation: 2 };
  const both = rememberAttempt(rememberAttempt([], a), b);
  assert.equal(both.length, 2);
  assert.equal(both[0].classroom_id, "A");
  assert.equal(both[0].title, "课堂甲");
  assert.deepEqual(both[0].request, {
    confirmation: "课堂甲", expected_revision: 4, idempotency_key: "request-key-for-A",
  });
  const retry: DeletionAttempt = { ...both[0], state: "sending", operation: 3, error: null };
  const retried = rememberAttempt(both, retry);
  assert.strictEqual(retried[0].request, a.request);
  assert.strictEqual(retried[1], b);
  assert.equal(retried[1].request.idempotency_key, "request-key-for-B");
  assert.throws(() => Object.defineProperty(a.request, "confirmation", { value: "课堂乙" }));
});

test("同一幂等键不能替换成另一课堂或另一确认版本", () => {
  const a = createAttempt("A", "课堂甲", 4, "request-key-for-A");
  const crossed = createAttempt("B", "课堂乙", 7, "request-key-for-A");
  assert.throws(() => rememberAttempt([a], crossed), /不能把已发起的删除请求快照替换/);
  const newerVersion = createAttempt("A", "课堂甲", 5, "request-key-for-A");
  assert.throws(() => rememberAttempt([a], newerVersion), /不能把已发起的删除请求快照替换/);
  assert.equal(a.request.expected_revision, 4);
});

test("迟到的旧操作不能将已取得任务的A回退为未知，也不覆盖B", () => {
  const original = createAttempt("A", "课堂甲", 4, "request-key-for-A");
  const unknown: DeletionAttempt = { ...original, operation: 1, state: "unknown" };
  const known: DeletionAttempt = { ...original, operation: 3, state: "known", task_id: "task-for-A" };
  const b = { ...createAttempt("B", "课堂乙", 7, "request-key-for-B"), operation: 2 };
  const previous = [known, b];
  const afterLateResponse = rememberAttempt(previous, unknown);
  assert.strictEqual(afterLateResponse, previous);
  assert.equal(afterLateResponse[0].state, "known");
  assert.equal(afterLateResponse[0].task_id, "task-for-A");
  assert.strictEqual(afterLateResponse[1], b);
});

test("任务按标识和版本更新，旧状态版本不能覆盖完成状态或另一任务", () => {
  const a = task("task-for-A", "A", 3);
  const b = task("task-for-B", "B", 2);
  const previous = [a, b];
  const oldA: DeletionView = {
    ...a, revision: 1, local_status: "pending", local_complete: false, remaining_files: 2,
  };
  assert.strictEqual(rememberTask(previous, oldA), previous);
  const updatedA = task("task-for-A", "A", 4);
  const afterUpdate = rememberTask(previous, updatedA);
  assert.equal(afterUpdate.length, 2);
  assert.strictEqual(afterUpdate[0], updatedA);
  assert.strictEqual(afterUpdate[1], b);
});

test("A删除完成时保留新选中的B和B的打开表单", () => {
  const selectedB = { selected: classroom("B"), formOpen: true };
  const afterA = selectionAfterRemoval(selectedB, "A");
  assert.strictEqual(afterA, selectedB);
  assert.equal(afterA.selected?.id, "B");
  assert.equal(afterA.formOpen, true);
  const creating = { selected: null, formOpen: true };
  assert.strictEqual(selectionAfterRemoval(creating, "A"), creating);
});

test("当前确实选中A时，A删除完成同时清空选择和A表单", () => {
  const selectedA = { selected: classroom("A"), formOpen: true };
  assert.deepEqual(selectionAfterRemoval(selectedA, "A"), { selected: null, formOpen: false });
  assert.equal(selectedA.selected.id, "A");
  assert.equal(selectedA.formOpen, true);
});
