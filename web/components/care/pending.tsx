"use client";

import { useState } from "react";
import { careApi } from "../../lib/care/api";
import type { Observation } from "../../lib/care/types";
import { CareObservation } from "./observation";
import styles from "./care.module.css";

export function PendingObservations({ items, active, onSaved }: {
  items: Observation[]; active: boolean; onSaved: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function confirm(item: Observation) {
    if (busy) return; setBusy(true); setMessage("");
    try { await careApi.confirmObservation(item); await onSaved(); setMessage("观察已确认并重新计算比较依据。"); }
    catch (failure) { setMessage(failure instanceof Error ? failure.message : "确认失败，请刷新来源。"); }
    finally { setBusy(false); }
  }
  if (items.length === 0) return null;
  return <section className={styles.card}><h2>待核验与来源变化的观察</h2>
    {items.map((item) => <div key={item.id}><CareObservation item={item} active={active} />
      {item.source_current && !item.confirmed ? <button type="button" disabled={busy}
        onClick={() => void confirm(item)}>已回听，确认这条观察</button>
        : <p>来源发生变化，请根据当前已核验发言重新记录，旧观察不进入比较。</p>}
    </div>)}
    {message && <p role="status">{message}</p>}
  </section>;
}
