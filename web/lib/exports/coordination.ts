export interface RequestToken { context: string; generation: number; }
export interface VersionedExport {
  id: string; revision: number; status: "active" | "revoked" | "stale" | "deleted";
}

export class ExportRequests {
  private context = "";
  private generation = 0;
  private pending = new Set<number>();

  begin(context: string): RequestToken {
    if (this.context !== context) { this.context = context; this.pending.clear(); }
    const token = { context, generation: ++this.generation };
    this.pending.add(token.generation);
    return token;
  }
  current(token: RequestToken, context: string): boolean {
    return token.context === context && this.context === context && token.generation === this.generation;
  }
  finish(token: RequestToken): void { this.pending.delete(token.generation); }
  count(): number { return this.pending.size; }
  cancel(): void { this.generation += 1; this.pending.clear(); }
}

export function preferExport<T extends VersionedExport>(previous: T | undefined, incoming: T): T {
  if (!previous) return incoming;
  if (previous.status !== "active" && incoming.status === "active") return previous;
  if (previous.revision > incoming.revision) return previous;
  return incoming;
}

export function mergeExportList<T extends VersionedExport>(previous: T[], incoming: T[]): T[] {
  return incoming.map((item) => preferExport(previous.find((old) => old.id === item.id), item));
}
