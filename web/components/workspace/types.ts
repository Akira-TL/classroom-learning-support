import type { Utterance } from "../../lib/speech";

export type WorkspaceView = "review" | "teaching" | "publishing";

export function speakerLabel(item: Utterance): string {
  if (item.source_kind === "recorded_result") {
    if (item.source_ref === "teacher") return "老师";
    if (item.source_ref === "all") return "集体应答";
    if (/^student-\d{2,4}$/.test(item.source_ref ?? "")) {
      return `学生${Number(item.source_ref?.replace("student-", ""))}`;
    }
  }
  return item.student_alias?.replace(/^student-0*/, "学生") ?? "学生归属待核验";
}

export function segmentKey(item: { session_id: string; segment_id: string }): string {
  return `${item.session_id}/${item.segment_id}`;
}

export function timeLabel(milliseconds: number): string {
  const seconds = Math.floor(milliseconds / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
