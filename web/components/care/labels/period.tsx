"use client";

import { useEffect, useState } from "react";
import { speech, type Utterance } from "../../../lib/speech";
import { tagNames, type TagBatch, type TagValue } from "../../../lib/care/labels/types";
import { AudioPanel } from "../../audio-panel";
import { timeLabel } from "../../workspace/types";
import styles from "./labels.module.css";

function TagAudio({ batch, tag, active }: { batch: TagBatch; tag: TagValue; active: boolean }) {
  const [source, setSource] = useState<Utterance | null>(null);
  const [message, setMessage] = useState("");
  useEffect(() => {
    let cancelled = false; setSource(null); setMessage("");
    speech.timeline(batch.classroom_id).then((items) => {
      if (cancelled) return;
      const item = items.find((entry) => entry.session_id === batch.session_id
        && entry.start_ms < tag.end_ms && entry.end_ms > tag.start_ms);
      if (item) setSource({ ...item, start_ms: Math.max(item.start_ms, tag.start_ms),
        end_ms: Math.min(item.end_ms, tag.end_ms) });
      else setMessage("该时间段尚无已接入的对应音频转写片段，请补齐同一会话的音频与转写数据。");
    }).catch((failure: unknown) => {
      if (!cancelled) setMessage(failure instanceof Error ? failure.message : "来源读取失败。");
    });
    return () => { cancelled = true; };
  }, [batch.classroom_id, batch.session_id, tag.start_ms, tag.end_ms]);
  return <div className={styles.audio}>{source ? <>
    <p>对应转写：{source.teacher_text ?? (source.upstream_text || "该片段没有识别文字")}</p>
    <AudioPanel classroomId={batch.classroom_id} utterance={source} active={active} onSaved={async () => {}} />
  </> : <p role="status">{message || "正在定位对应片段…"}</p>}</div>;
}

export function LabelPeriod({ title, batches, active, allowAudio }: {
  title: string; batches: TagBatch[]; active: boolean; allowAudio: boolean;
}) {
  const [selected, setSelected] = useState("");
  return <section className={styles.period}><h3>{title}</h3>
    {batches.length === 0 && <p>尚未导入该时段标签，不能记为零次。</p>}
    {batches.map((batch) => {
      const extent = batch.captured_duration_ms ?? Math.max(...batch.tags.map((tag) => tag.end_ms), 1);
      return <article key={batch.id} className={styles.batch}>
        <header><time>{batch.observed_on}</time>
          <span>{batch.data_origin === "demonstration" ? "演示样例" : "提供的标注"}</span></header>
        <p>{batch.source_name} · 来源版本 {batch.source_version}</p>
        <p>{batch.source_description}</p>
        <p className={styles.muted}>{batch.captured_duration_ms === null
          ? "采集时长未提供，时间条仅覆盖已标注范围" : `已提供采集时长 ${timeLabel(batch.captured_duration_ms)}`}</p>
        <div className={styles.timeline} aria-label={`${title}标签时间分布`}>
          {batch.tags.map((tag) => <button key={tag.tag_id} type="button"
            aria-label={`${tag.original_label} ${timeLabel(tag.start_ms)}至${timeLabel(tag.end_ms)}`}
            title={`${tag.original_label} · ${tag.count}次`} onClick={() => setSelected(`${batch.id}/${tag.tag_id}`)}
            style={{ left: `${tag.start_ms / extent * 100}%`,
              width: `${Math.max(.8,(tag.end_ms - tag.start_ms) / extent * 100)}%` }} />)}
        </div>
        <div className={styles.times}><span>00:00</span><span>{timeLabel(extent)}</span></div>
        {batch.tags.map((tag) => <div key={tag.tag_id} className={styles.tag}>
          <button type="button" aria-pressed={selected === `${batch.id}/${tag.tag_id}`}
            onClick={() => setSelected(`${batch.id}/${tag.tag_id}`)}>{tagNames[tag.label]} · {tag.count} 次 ·
            {timeLabel(tag.start_ms)}—{timeLabel(tag.end_ms)}</button>
          {tag.category === "external_state" && <p>外部状态标签，来源待核实；声音本身不能证明{tag.original_label}。</p>}
          {tag.note && <p>{tag.note}</p>}
          {selected === `${batch.id}/${tag.tag_id}` && <>
            {allowAudio && batch.transcripts.filter((line) => line.start_ms < tag.end_ms
              && line.end_ms > tag.start_ms).map((line, index) => <blockquote key={index}>
                提供的转写：{line.text}</blockquote>)}
            {allowAudio ? <TagAudio batch={batch} tag={tag} active={active} /> : <p>汇总视角不展示个人音频。</p>}
          </>}
        </div>)}
      </article>;
    })}
  </section>;
}
