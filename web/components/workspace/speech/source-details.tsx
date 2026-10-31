import type { Utterance } from "../../../lib/speech";
import { reliabilityNames } from "../../../lib/speech/native";
import styles from "../workspace.module.css";

const failureNames: Record<string, string> = {
  asr_unavailable: "语音识别引擎不可用", no_speech_recognized: "未识别出文字",
};

export function SourceDetails({ utterance }: { utterance: Utterance }) {
  const event = utterance.native_event;
  if (!event) return null;
  const reasons = event.diagnostics?.math_guard?.review_reasons ?? [];
  return <details className={styles.audit}>
    <summary>声源线索与处理状态</summary>
    <p>这些线索只用于协助教师核验，学生归属仍需单独确认。</p>
    {event.reliability_state && <p>处理可靠性：{reliabilityNames[event.reliability_state]}</p>}
    {event.status && <p>处理状态：{failureNames[event.status] ?? event.status}</p>}
    {event.sources.length === 0 && <p>上游未提供声源线索。</p>}
    {event.sources.map((source) => <p key={`${source.source_id}-${source.valid_from_ms}`}>
      {source.kind === "azimuth" ? `声源方位：${source.value}°` : `匿名说话人：${source.value}`}
      {` · ${source.valid_from_ms}—${source.valid_to_ms} 毫秒 · ${reliabilityNames[source.reliability_state]}`}
      {source.rebind_hint && " · 声源发生变化，请重新核验学生归属"}
    </p>)}
    {event.overlap?.present && <p>重叠片段：
      {(event.overlap.with ?? event.overlap.with_segments ?? []).join("、") || "上游未指定其他片段"}</p>}
    {reasons.length > 0 && <><h3>数学转写核验提示</h3><ul>
      {reasons.map((reason, index) => <li key={index}>{reason}</li>)}
    </ul></>}
    {event.diagnostics?.math_guard?.policy && <p>{event.diagnostics.math_guard.policy}</p>}
    {event.diagnostics?.engine && <p>识别引擎：{event.diagnostics.engine}</p>}
  </details>;
}
