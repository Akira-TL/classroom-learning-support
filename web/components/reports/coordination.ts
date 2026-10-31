import type { ParentReport } from "../../lib/reports";

export interface ReportToken {
  readonly source: string; readonly epoch: number; readonly id: number; readonly kind: "list" | "operation";
}
export class ParentReportRequests {
  private source = "";
  private epoch = 0;
  private nextOperation = 0;
  private operation: number | null = null;
  private list = 0;

  setSource(source: string): void {
    if (this.source === source) return;
    this.source = source; this.cancel();
  }
  beginList(source: string): ReportToken | null {
    return source === this.source ? { source, epoch: this.epoch, id: ++this.list, kind: "list" } : null;
  }
  beginOperation(source: string, mutation: boolean): ReportToken | null {
    if (source !== this.source || this.operation !== null) return null;
    this.operation = ++this.nextOperation;
    if (mutation) this.list++;
    return { source, epoch: this.epoch, id: this.operation, kind: "operation" };
  }
  current(token: ReportToken): boolean {
    return token.source === this.source && token.epoch === this.epoch
      && token.id === (token.kind === "list" ? this.list : this.operation);
  }
  finish(token: ReportToken): boolean {
    if (token.kind !== "operation" || !this.current(token)) return false;
    this.operation = null; return true;
  }
  cancel(): void { this.epoch++; this.list++; this.operation = null; }
}
export function preferParentReport(previous: ParentReport | undefined, incoming: ParentReport): ParentReport {
  if (!previous) return incoming;
  return previous.revision > incoming.revision || previous.status !== "published" && incoming.status === "published"
    ? previous : incoming;
}
export function mergeParentReports(previous: ParentReport[], incoming: ParentReport[]): ParentReport[] {
  return incoming.map((item) => preferParentReport(previous.find((old) => old.id === item.id), item));
}
