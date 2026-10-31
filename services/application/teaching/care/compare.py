import sqlite3
from statistics import mean
from typing import Literal

from .models import CompareRequest, Comparison, MetricComparison, Observation
from .store import CareStore


def compare(db: sqlite3.Connection, store: CareStore, teacher: str, request: CompareRequest) -> Comparison:
    records = [item for item in store.list_observations(db, teacher)
               if item.student_id == request.student_id and item.confirmed and item.source_current]
    baseline = [item for item in records if request.baseline_start <= item.observed_on <= request.baseline_end]
    recent = [item for item in records if request.current_start <= item.observed_on <= request.current_end]
    conditions = {item.capture_conditions for item in baseline + recent}
    notes: list[str] = []
    if len(baseline) < 3 or len(recent) < 3:
        notes.append("至少一个时间段少于3条已核验观察，样本不足以描述稳定变化；保留逐条事实供教师了解")
    if len(conditions) > 1:
        notes.append("采集条件不同，数值不作直接差值解释；请先核对设备、距离、环境和任务")
    metrics = [metric("pitch_hz", "Hz", baseline, recent, len(conditions) == 1),
               metric("level_dbfs", "dBFS", baseline, recent, len(conditions) == 1)]
    return Comparison(periods=request, baseline=baseline, current=recent, metrics=metrics, notes=notes)


def metric(name: Literal["pitch_hz", "level_dbfs"], unit: Literal["Hz", "dBFS"],
           baseline: list[Observation], recent: list[Observation],
           same_conditions: bool) -> MetricComparison:
    def values(items: list[Observation]) -> list[float]:
        measured = [item.measurements.pitch_hz if name == "pitch_hz" else item.measurements.level_dbfs
                    for item in items if item.measurements]
        return [value for value in measured if value is not None]

    before, after = values(baseline), values(recent)
    methods = {item.measurements.method for item in baseline + recent if item.measurements}
    comparable = same_conditions and len(methods) == 1 and len(before) >= 3 and len(after) >= 3
    return MetricComparison.model_validate({
        "name": name, "unit": unit, "baseline_count": len(before), "current_count": len(after),
        "baseline_mean": mean(before) if before else None, "current_mean": mean(after) if after else None,
        "difference": mean(after) - mean(before) if comparable else None, "comparable": comparable,
        "explanation": "同一学生、相同记录条件和测量方法下的描述性差值，不作情绪或健康推断" if comparable
        else "可靠测量缺失、样本不足或条件/方法不一致，暂不计算差值",
    })
