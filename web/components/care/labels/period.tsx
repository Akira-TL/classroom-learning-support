"use client";

import { useState } from "react";
import { tagNames, type TagBatch, type TagValue } from "../../../lib/care/labels/types";
import { BatchAudio } from "./audio";
import { timeLabel } from "../../workspace/types";
import styles from "./labels.module.css";

export function LabelPeriod({ title, batches, active, allowAudio, onSaved }: {
  title: string; batches: TagBatch[]; active: boolean; allowAudio: boolean; onSaved: () => void;
}) {
  const [selected, setSelected] = useState("");
  const [range, setRange] = useState<{ start: number; end: number } | null>(null);
  function select(batch: TagBatch, tag: TagValue) {
    setSelected(`${batch.id}/${tag.tag_id}`); setRange({ start: tag.start_ms, end: tag.end_ms });
  }
  return <section className={styles.period}><h3>{title}</h3>
    {batches.length === 0 && <p>尚未导入该时段标签，不能记为零次。</p>}
    {batches.map((batch) => {
      const extent = batch.captured_duration_ms ?? Math.max(...batch.tags.map((tag) => tag.end_ms), 1);
      const demonstration = batch.data_origin === "demonstration";
      return <article key={batch.id} className={styles.batch}>
        <header><time>{batch.observed_on}</time>
          {!demonstration && <span>提供的标注</span>}</header>
        {!demonstration && <><p>{batch.source_name} · 来源版本 {batch.source_version}</p>
          <p>{batch.source_description}</p></>}
        <p className={styles.muted}>{batch.captured_duration_ms === null
          ? "完整时长未知" : `时长 ${timeLabel(batch.captured_duration_ms)}`}</p>
        <div className={styles.timeline} aria-label={`${title}标签时间分布`}>
          {batch.tags.map((tag) => <button key={tag.tag_id} type="button"
            aria-label={`${tag.original_label} ${timeLabel(tag.start_ms)}至${timeLabel(tag.end_ms)}`}
            title={`${tag.original_label} · ${tag.count}次`} onClick={() => select(batch, tag)}
            style={{ left: `${tag.start_ms / extent * 100}%`,
              width: `${Math.max(.8,(tag.end_ms - tag.start_ms) / extent * 100)}%` }} />)}
        </div>
        <div className={styles.times}><span>00:00</span><span>{timeLabel(extent)}</span></div>
        {batch.tags.map((tag) => <div key={tag.tag_id} className={styles.tag}>
          <button type="button" aria-pressed={selected === `${batch.id}/${tag.tag_id}`}
            onClick={() => select(batch, tag)}>{tagNames[tag.label]} · {tag.count} 次 ·
            {timeLabel(tag.start_ms)}—{timeLabel(tag.end_ms)}</button>
          {!demonstration && tag.category === "external_state"
            && <p>外部状态标签，来源待核实；声音本身不能证明{tag.original_label}。</p>}
          {!demonstration && tag.note && <p>{tag.note}</p>}
          {selected === `${batch.id}/${tag.tag_id}` && <>
            {allowAudio && batch.transcripts.filter((line) => line.start_ms < tag.end_ms
              && line.end_ms > tag.start_ms).map((line, index) => <blockquote key={index}>
                <button type="button" onClick={() => setRange({ start: line.start_ms, end: line.end_ms })}>
                  {timeLabel(line.start_ms)}—{timeLabel(line.end_ms)} · {line.text}</button></blockquote>)}
            {allowAudio ? <BatchAudio batch={batch} startMs={range?.start ?? tag.start_ms}
              endMs={range?.end ?? tag.end_ms} active={active} onSaved={onSaved} />
              : <p>汇总视角不展示个人音频。</p>}
          </>}
        </div>)}
      </article>;
    })}
  </section>;
}

