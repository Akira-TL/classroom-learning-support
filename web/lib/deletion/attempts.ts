import type { DeleteInput, DeletionView } from "./api";
import type { Classroom } from "../types";

export interface ClassroomSelection { selected: Classroom | null; formOpen: boolean; }
export function selectionAfterRemoval(previous: ClassroomSelection, deletedId: string): ClassroomSelection {
  return previous.selected?.id === deletedId ? { selected: null, formOpen: false } : previous;
}

export interface DeletionAttempt {
  readonly classroom_id: string;
  readonly title: string;
  readonly request: Readonly<DeleteInput>;
  state: "sending" | "unknown" | "known";
  operation: number;
  task_id: string | null;
  error: string | null;
}
export function createAttempt(cid: string, title: string, revision: number, key: string): DeletionAttempt {
  return {
    classroom_id: cid, title,
    request: Object.freeze({ confirmation: title, expected_revision: revision, idempotency_key: key }),
    state: "sending", operation: 0, task_id: null, error: null,
  };
}
export function rememberAttempt(previous: DeletionAttempt[], incoming: DeletionAttempt): DeletionAttempt[] {
  const old = previous.find((item) => item.request.idempotency_key === incoming.request.idempotency_key);
  if (old && (old.classroom_id !== incoming.classroom_id || old.title !== incoming.title
    || JSON.stringify(old.request) !== JSON.stringify(incoming.request))) {
    throw new Error("不能把已发起的删除请求快照替换为另一课堂或版本。");
  }
  if (old && old.operation > incoming.operation) return previous;
  return old ? previous.map((item) => item === old ? incoming : item) : [...previous, incoming];
}
export function rememberTask(previous: DeletionView[], incoming: DeletionView): DeletionView[] {
  const old = previous.find((item) => item.id === incoming.id);
  if (old && old.revision > incoming.revision) return previous;
  return old ? previous.map((item) => item.id === incoming.id ? incoming : item) : [...previous, incoming];
}
