export type WorkspaceView = "review" | "teaching" | "publishing";

export function segmentKey(item: { session_id: string; segment_id: string }): string {
  return `${item.session_id}/${item.segment_id}`;
}

export function timeLabel(milliseconds: number): string {
  const seconds = Math.floor(milliseconds / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
