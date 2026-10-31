import assert from "node:assert/strict";
import test from "node:test";
import {
  choosePublicationTask, publicationContext, publicationReady, publicationRecord,
} from "./publication-source.ts";

const evidence = { id: "evidence-A", classroom_id: "class-A", revision: 3, status: "confirmed" as const };
const record = { id: "exercise-A", classroom_id: "class-A", evidence_id: "evidence-A",
  evidence_revision: 3, status: "confirmed" as const, teacherDraft: "保留教师编辑" };
const ready = { context: publicationContext("class-A", evidence), status: "ready" as const };

test("同一课堂、依据和已核实列表允许原记录，不复制或丢失教师稿", () => {
  assert.equal(publicationReady("class-A", evidence, ready), true);
  assert.equal(publicationRecord(record, "class-A", evidence, ready, "succeeded"), record);
});
test("来源版本或状态变化，即使上一轮列表成功也立即只读失效", () => {
  for (const source of [{ ...evidence, revision: 4 }, { ...evidence, status: "stale" as const },
    { ...evidence, id: "evidence-B" }, { ...evidence, classroom_id: "class-B" }]) {
    const incoming = publicationRecord(record, "class-A", source, ready, "succeeded");
    assert.equal(incoming.status, "stale");
    assert.equal(incoming.teacherDraft, "保留教师编辑");
    assert.equal(record.status, "confirmed");
  }
});
test("读取中和读取失败不得沿用旧发布预览的有效来源", () => {
  for (const status of ["loading", "error"] as const) {
    const read = { ...ready, status };
    assert.equal(publicationReady("class-A", evidence, read), false);
    assert.equal(publicationRecord(record, "class-A", evidence, read, "succeeded").status, "stale");
  }
});
test("不同课堂或不同依据记录、旧版本与未成功任务均不可发布", () => {
  for (const value of [{ ...record, classroom_id: "class-B" }, { ...record, evidence_id: "evidence-B" },
    { ...record, evidence_revision: 2 }]) {
    assert.equal(publicationRecord(value, "class-A", evidence, ready, "succeeded").status, "stale");
  }
  for (const status of ["running", "failed", "stale"] as const) {
    assert.equal(publicationRecord(record, "class-A", evidence, ready, status).status, "stale");
  }
});
test("同一来源仍保留未确认、驳回或失效原状态，不能提升成已确认", () => {
  for (const status of ["pending", "rejected", "stale"] as const) {
    assert.equal(publicationRecord({ ...record, status }, "class-A", evidence, ready, "succeeded").status, status);
  }
});
test("默认最新有效任务，刷新保留原选择，缺失时才重新选择", () => {
  const items = [{ id: "old", valid: true }, { id: "new", valid: true }, { id: "failed", valid: false }];
  assert.equal(choosePublicationTask("", items), "new");
  assert.equal(choosePublicationTask("old", items), "old");
  assert.equal(choosePublicationTask("failed", items), "failed");
  assert.equal(choosePublicationTask("missing", items), "new");
  assert.equal(choosePublicationTask("", [{ id: "only-failed", valid: false }]), "only-failed");
  assert.equal(choosePublicationTask("old", []), "");
});
