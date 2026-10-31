import assert from "node:assert/strict";
import test from "node:test";
import { countLabel, minuteRate, seats } from "./presentation.ts";

test("缺失标签不是零次；缺少时长不画频率", () => {
  assert.equal(countLabel(null), "暂无数据");
  assert.equal(countLabel(0), "0 次");
  assert.equal(minuteRate(null), "采集时长缺失，不计算频率");
  assert.equal(minuteRate(120), "2.00 次/分钟");
});

test("演示座位稳定对应名单，空位不分配不存在的学生", () => {
  const layout = seats(["student-01", "student-02"]);
  assert.equal(layout.length, 12);
  assert.equal(layout[0].student, "student-01");
  assert.equal(layout[1].student, "student-02");
  assert.equal(layout.filter((seat) => seat.student === null).length, 10);
  assert.deepEqual(seats(["student-01", "student-02"]), layout);
});
