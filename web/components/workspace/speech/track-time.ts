export function trackWindow(startMs: number, endMs: number, offsetMs: number, duration: number) {
  const start = Math.max(0, (startMs - offsetMs) / 1000);
  const end = Math.min(duration, (endMs - offsetMs) / 1000);
  return { start, end, available: end > start };
}

export function alignedPosition(sessionMs: number, offsetMs: number, start: number, end: number) {
  return Math.min(Math.max((sessionMs - offsetMs) / 1000, start), end);
}
