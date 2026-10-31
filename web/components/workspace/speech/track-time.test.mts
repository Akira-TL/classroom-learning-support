import test from "node:test";
import assert from "node:assert/strict";
import { alignedPosition, trackWindow } from "./track-time.ts";

test("原音频与从片段起点保存的处理音轨覆盖同一会话范围", () => {
  assert.deepEqual(trackWindow(12000, 18000, 0, 40), { start: 12, end: 18, available: true });
  assert.deepEqual(trackWindow(12000, 18000, 12000, 6), { start: 0, end: 6, available: true });
  assert.equal(alignedPosition(14500, 0, 12, 18), 14.5);
  assert.equal(alignedPosition(14500, 12000, 0, 6), 2.5);
});

test("不相交或过短音轨不得假装覆盖完整片段；切换定位不能越界", () => {
  assert.equal(trackWindow(12000, 18000, 20000, 6).available, false);
  assert.deepEqual(trackWindow(12000, 18000, 12000, 3), { start: 0, end: 3, available: true });
  assert.equal(alignedPosition(9000, 12000, 0, 6), 0);
  assert.equal(alignedPosition(25000, 12000, 0, 6), 6);
});
