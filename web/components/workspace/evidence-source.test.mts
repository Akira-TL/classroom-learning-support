import assert from "node:assert/strict";
import test from "node:test";
import { evidenceForSource } from "./evidence-source.ts";
import type { EvidenceRecord } from "../../lib/evidence.ts";
import type { Utterance } from "../../lib/speech.ts";
import type { Classroom } from "../../lib/types.ts";

const classroom: Classroom = {
  id: "class-1", teacher_id: "teacher-01", revision: 1, title: "分数", date: "2026-10-31",
  objective: "比较面积", students: ["student-01", "student-02"], source: "合成资料", authorization: "演示",
  questions: [{ id: "question-1", text: "四块是否一定等大？", reference_answer: "不一定",
    diagram_required: true, diagram_description: "4:2:1:1" }],
};
const utterance: Utterance = {
  session_id: "session-1", segment_id: "segment-1", revision: 1, sequence: 1, phase: "final",
  source_kind: "synthetic", start_ms: 12000, end_ms: 18000, upstream_text: "不一定等大",
  source_ref: null, overlap: false, version: 3, teacher_text: null, student_alias: "student-01",
  question_id: "question-1", text_review: "confirmed", identity_review: "confirmed", question_review: "confirmed",
  reviewed_by: "teacher-01", audio_available: false,
};
const context: EvidenceRecord["basis"]["context"] = {
  question_id: "question-1", question_revision: 1, objective: "比较面积", question: "四块是否一定等大？",
  reference_answer: "不一定", diagram_required: true, diagram_description: "4:2:1:1",
  utterance_id: "segment-1", utterance_revision: 3, student_alias: "student-01", utterance: "不一定等大",
  text_confirmed: true, identity_confirmed: true, question_confirmed: true,
};
const content = { quote: "不一定等大", interpretation: "能注意面积", limitation: "单次回答", follow_up_question: "解释依据" };
const record: EvidenceRecord = {
  id: "evidence-1", task_id: "task-1", classroom_id: "class-1", revision: 2,
  basis: { session_id: "session-1", segment_id: "segment-1", utterance_version: 3,
    question_fingerprint: "fixed-question-fingerprint", context },
  original: { context, content, model: "deepseek", status: "pending_teacher_review" },
  content, status: "confirmed", reviewed_by: "teacher-01",
};

test("当前依据和仅改课堂标题保留已确认状态", () => {
  assert.equal(evidenceForSource(record, classroom, utterance), record);
  const renamed = { ...classroom, title: "新标题", revision: 2 };
  assert.equal(evidenceForSource(record, renamed, utterance), record);
});
test("身份或发言版本变化立即停止展示为已确认，不等待列表刷新", () => {
  const corrected = evidenceForSource(record, classroom, { ...utterance, student_alias: "student-02", version: 4 });
  assert.equal(corrected.status, "stale");
  assert.equal(corrected.content, record.content);
  assert.equal(corrected.original, record.original);
  assert.equal(evidenceForSource(record, classroom, { ...utterance, version: 4 }).status, "stale");
});
test("教学目标、题干或图形依据变化使旧证据失效", () => {
  assert.equal(evidenceForSource(record, { ...classroom, objective: "新目标" }, utterance).status, "stale");
  const changed = { ...classroom, questions: [{ ...classroom.questions[0], diagram_description: "1:1:1:1" }] };
  assert.equal(evidenceForSource(record, changed, utterance).status, "stale");
  assert.equal(evidenceForSource(record, { ...classroom, questions: [] }, utterance).status, "stale");
});
test("原记录已失效时即使当前文字相同也不能自行恢复有效", () => {
  const stale: EvidenceRecord = { ...record, status: "stale" };
  assert.equal(evidenceForSource(stale, classroom, utterance).status, "stale");
});
