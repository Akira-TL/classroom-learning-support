import assert from "node:assert/strict";
import test from "node:test";
import { batchAudioAssetSchema, recipientExplanationSchema, tagBatchSchema,
  tagImportSchema, tagSchema } from "./types.ts";

test("导入保留上游标签原值、带时间转写和演示来源，不要求确认发布", () => {
  const value = tagImportSchema.parse({ import_id: "import-1", student_id: "student-01", observed_on: "2026-10-31",
    session_id: "session-1", source_name: "用户标注", source_version: "1", source_description: "人工外部标注",
    data_origin: "demonstration", capture_conditions: "同一设备", tags: [{ tag_id: "1", label: "inattention",
      original_label: "走神", category: "external_state", start_ms: 1000, end_ms: 2000, count: 1,
      original_value: "来源待核实" }], transcripts: [{ start_ms: 1000, end_ms: 2000, text: "提供的原话" }] });
  assert.equal(value.confirmed, false);
  assert.equal(value.tags[0].original_value, "来源待核实");
  assert.equal(value.transcripts[0].text, "提供的原话");
  assert.equal(value.data_origin, "demonstration");
});

test("拒绝把外部走神标成声音事实，拒绝逆向时间", () => {
  const tag = { tag_id: "1", label: "inattention", original_label: "走神", category: "audible_event",
    start_ms: 1000, end_ms: 2000, count: 1 };
  assert.equal(tagSchema.safeParse(tag).success, false);
  assert.equal(tagSchema.safeParse({ ...tag, category: "external_state", end_ms: 500 }).success, false);
});

test("学生家长响应无需内部比较数据，也不能作为教师预览响应使用", () => {
  const response = { id: "r", student_id: "student-01", perspective: "student", source_fingerprint: "source-1",
    model: "deepseek", status: "generated", content: { summary: "根据提供记录", change_explanation: "需结合情况了解",
      followup_questions: ["采集条件是否一致？"], followup: "与教师交流" } };
  assert.equal(recipientExplanationSchema.safeParse(response).success, true);
  assert.equal(recipientExplanationSchema.safeParse({ ...response, perspective: "teacher" }).success, false);
});

test("标签批次在没有语音事件时也能承载会话原声，未上传时保持缺失", () => {
  const payload = { import_id: "import-1", student_id: "student-01", observed_on: "2026-10-31",
    session_id: "only-tags", source_name: "用户标注", source_version: "1", source_description: "独立标签数据",
    data_origin: "provided_annotation", capture_conditions: "同一设备", tags: [{ tag_id: "1", label: "cough",
      original_label: "咳嗽", category: "audible_event", start_ms: 1000, end_ms: 2000, count: 1 }],
    id: "batch-1", classroom_id: "class-1", teacher_id: "teacher-01", revision: 1 };
  assert.equal(tagBatchSchema.parse(payload).audio_asset, null);
  const audio = { id: "audio-1", session_id: "only-tags", duration_ms: 5000,
    channels: 1, sample_rate: 16000, source: "teacher_uploaded_audio" };
  assert.deepEqual(tagBatchSchema.parse({ ...payload, audio_asset: audio }).audio_asset, audio);
  assert.equal(batchAudioAssetSchema.safeParse({ ...audio, duration_ms: 0 }).success, false);
});
