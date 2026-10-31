import sqlite3

from ..models import CompareRequest
from .models import TagBatch, TagComparison, TagLabel, TagSummary
from .store import TagStore

LABELS: tuple[TagLabel, ...] = ("cough", "pen_sound", "snoring", "inattention", "sleeping", "other")


def summary(label: TagLabel, baseline: list[TagBatch], current: list[TagBatch]) -> TagSummary:
    before = [batch for batch in baseline if any(tag.label == label for tag in batch.tags)]
    after = [batch for batch in current if any(tag.label == label for tag in batch.tags)]

    def count(items: list[TagBatch]) -> int | None:
        return sum(tag.count for batch in items for tag in batch.tags if tag.label == label) if items else None

    def duration(items: list[TagBatch]) -> int | None:
        if not items or any(batch.captured_duration_ms is None for batch in items):
            return None
        return sum(batch.captured_duration_ms for batch in items if batch.captured_duration_ms is not None)

    bc, cc, bd, cd = count(before), count(after), duration(before), duration(after)
    br = bc * 3600000 / bd if bc is not None and bd else None
    cr = cc * 3600000 / cd if cc is not None and cd else None
    conditions = {batch.capture_conditions for batch in before + after}
    notes = []
    if bc is None or cc is None:
        notes.append("至少一个时间段未提供此标签记录，缺失不视为零次")
    if bd is None or cd is None:
        notes.append("采集时长缺失或未覆盖该标签，不能计算每小时次数")
    if len(conditions) > 1:
        notes.append("采集条件不同，仅展示记录次数和各自率，不计算率差值")
    if label in {"inattention", "sleeping"}:
        notes.append("这是提供者的外部状态标注，须核实观察依据，不能仅由声音推断")
    return TagSummary(label=label, baseline_count=bc, current_count=cc,
                      count_difference=cc - bc if bc is not None and cc is not None else None,
                      baseline_duration_ms=bd, current_duration_ms=cd, baseline_per_hour=br, current_per_hour=cr,
                      rate_difference=cr - br if cr is not None and br is not None and len(conditions) == 1 else None,
                      notes=notes)


def compare_tags(db: sqlite3.Connection, store: TagStore, teacher: str, periods: CompareRequest) -> TagComparison:
    records = [item for item in store.listing(db, teacher) if item.student_id == periods.student_id]
    baseline = [item for item in records if periods.baseline_start <= item.observed_on <= periods.baseline_end]
    recent = [item for item in records if periods.current_start <= item.observed_on <= periods.current_end]
    return TagComparison(periods=periods, baseline=baseline, current=recent,
                         summaries=[summary(label, baseline, recent) for label in LABELS], notes=[
                             "标签来自所注明的外部材料及其标注信息，不代表本系统检测算法的实测能力",
                             "次数变化需结合采集时长、设备、距离、环境和标注口径；不作疾病或情绪判断",
                             "未核实来源标签参与描述性统计，但其真实性和学生归属仍以提供者材料为依据",
                         ])
