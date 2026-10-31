"use client";

import { useState } from "react";
import { labelsApi } from "../../../lib/care/labels/api";
import { tagImportSchema } from "../../../lib/care/labels/types";
import styles from "../care.module.css";

export function LabelImport({ classroomId, student, onSaved }: {
  classroomId: string; student: string; onSaved: () => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function read(file: File | undefined) {
    if (!file) return;
    if (file.size > 1024 * 1024) { setMessage("标签文件应小于1MB。"); return; }
    setText(await file.text()); setMessage("已读取文件，尚未导入。");
  }
  async function submit() {
    if (busy) return; setBusy(true); setMessage("");
    try {
      const input: unknown = JSON.parse(text);
      const payload = tagImportSchema.parse(input);
      if (payload.student_id !== student) throw new Error("文件中的学生与当前选择不一致，请先核对学生。");
      await labelsApi.import(classroomId, payload); onSaved();
      setMessage("标签已导入，将按原始来源和时间显示；没有运行标签检测或训练。");
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : "导入失败，请检查格式。");
    } finally { setBusy(false); }
  }
  return <details className={styles.card}><summary>导入音频对应的标签与时间戳</summary>
    <p>在此选择标签JSON文件或粘贴内容。音频与转写通过课堂音频入口接入；session_id应与音频会话一致。</p>
    <label>标签文件<input type="file" accept=".json,application/json" disabled={busy}
      onChange={(event) => void read(event.target.files?.[0])} /></label>
    <label>标签JSON<textarea rows={8} value={text}
      onChange={(event) => setText(event.target.value)} disabled={busy} /></label>
    <button type="button" disabled={busy || !text.trim()} onClick={() => void submit()}>
      {busy ? "导入中…" : "导入当前学生标签"}</button>
    <details><summary>查看导入格式与来源要求</summary>
      <p>data_origin使用provided_annotation表示提供的标注，demonstration表示演示样例。
        走神、睡觉必须使用external_state并说明外部来源，不能标为由声音直接判断。</p>
      <pre>{JSON.stringify({ import_id: "替换为不重复的导入标识", student_id: student, observed_on: "2026-10-31",
        session_id: "替换为音频会话标识", source_name: "格式示例", source_version: "1",
        source_description: "请填写标签由谁、用什么方式产生", data_origin: "demonstration",
        capture_conditions: "请填写设备和环境", captured_duration_ms: null,
        identity_confirmed: false, confirmed: false,
        transcripts: [{ start_ms: 1000, end_ms: 2000, text: "替换为对应时间的转写原文" }],
        tags: [{ tag_id: "tag-01", label: "cough", original_label: "咳嗽",
          category: "audible_event", start_ms: 1000, end_ms: 2000, count: 1, note: "格式示例，替换为实际标注" }] }, null, 2)}</pre>
    </details>{message && <p role="status">{message}</p>}
  </details>;
}
