import assert from "node:assert/strict";
import test from "node:test";
import { nativeEventSchema } from "./native.ts";

test("无文字失败保留声源、可靠性、音轨偏移及数学核验提示", () => {
  const event = nativeEventSchema.parse({
    protocol_version: "speech.v0.1", session_id: "s", event_id: "e", sequence: 4,
    event_type: "transcript.final", data_origin: "live", text: null, reliability_state: "failed",
    status: "asr_unavailable", overlap: { present: true, with_segments: ["other"] },
    sources: [{ source_id: "source", kind: "azimuth", value: 32, unit: "deg", reference: "mic_pair_broadside",
      valid_from_ms: 12000, valid_to_ms: 18000, reliability_state: "needs_review", rebind_hint: true }],
    audio_ref: [{ id: "raw", kind: "raw" }, { id: "sep", kind: "separated", offset_ms: 12000 }],
    diagnostics: { math_guard: { review_reasons: ["四/十需核验"] } },
  });
  assert.equal(event.text, null);
  assert.equal(event.sources[0].rebind_hint, true);
  assert.equal(event.audio_ref[1].offset_ms, 12000);
  assert.equal(event.overlap?.with_segments?.[0], "other");
  assert.deepEqual(event.diagnostics?.math_guard?.review_reasons, ["四/十需核验"]);
});
