"use client";

import { useEffect, useState } from "react";
import { evidenceApi, type GenerationResult } from "../../../lib/evidence";

export function useQuestionEvidence(classroomId: string, active: boolean) {
  const [results, setResults] = useState<GenerationResult[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      try {
        const incoming = await evidenceApi.list(classroomId);
        if (!cancelled) { setResults(incoming); setError(""); }
      } catch (failure) {
        if (!cancelled) {
          setResults([]);
          setError(failure instanceof Error ? failure.message : "学习证据读取失败。");
        }
      }
      if (!cancelled) timer = setTimeout(() => void load(), 5000);
    }
    void load();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [classroomId, active]);
  return { results, error };
}
