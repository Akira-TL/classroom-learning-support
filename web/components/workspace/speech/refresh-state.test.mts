import assert from "node:assert/strict";
import test from "node:test";
import { SpeechRefreshState } from "./refresh-state.ts";

test("手动刷新开始后的忙碌状态不能丢弃其响应", () => {
  const state = new SpeechRefreshState();
  const poll = state.begin();
  const manual = state.begin();
  state.busy = true;
  assert.equal(state.accepts(poll), false);
  assert.equal(state.accepts(manual), true);
  state.busy = false;
  assert.equal(state.accepts(manual), true);
});

test("较晚开始的读取和离开课堂仍能拒绝旧响应", () => {
  const state = new SpeechRefreshState();
  const old = state.begin();
  const current = state.begin();
  assert.equal(state.accepts(old), false);
  assert.equal(state.accepts(current), true);
  state.invalidate();
  assert.equal(state.accepts(current), false);
});
