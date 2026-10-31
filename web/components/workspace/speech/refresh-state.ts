export class SpeechRefreshState {
  private sequence = 0;
  busy = false;
  begin() { return ++this.sequence; }
  accepts(sequence: number) { return sequence === this.sequence; }
  invalidate() { ++this.sequence; }
}
