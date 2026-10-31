from datetime import date

import pytest
from pydantic import ValidationError
from test_evidence import Environment
from test_evidence import environment as environment

from teaching.care.models import CompareRequest
from teaching.care.tags.models import TagBatch, TagComparison, TagImport, TagLabel, TagValue


@pytest.mark.parametrize(("label", "original"), [
    ("sneeze", "打喷嚏"), ("chair_movement", "移动板凳"), ("door_close", "关门声"),
    ("desk_tap", "拍桌声"), ("pen_drop", "摔笔声"),
])
def test_recorded_events_import_and_compare_without_changing_origin(
    environment: Environment, label: TagLabel, original: str,
):
    tag = TagValue(tag_id="source-1", label=label, original_label=original, category="audible_event",
                   start_ms=3000, end_ms=4000, count=2, note="人工记录，归属尚待核对")
    request = TagImport(
        import_id="recorded", student_id="student-01", observed_on=date(2026, 10, 31),
        session_id="recorded-session", source_name="用户声音事件报告", source_version="1",
        source_description="用户提供的人工时间标注，不是本系统检测结果",
        data_origin="provided_annotation", capture_conditions="录制混音，声源位置尚未测量",
        captured_duration_ms=60000, tags=[tag],
    )
    url = f"/api/classrooms/{environment.cid}/care/tag-batches"
    response = environment.client.post(url, content=request.model_dump_json(),
                                       headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    imported = TagBatch.model_validate_json(response.content)
    assert imported.data_origin == "provided_annotation"
    assert imported.tags == [tag]
    assert not imported.confirmed and not imported.identity_confirmed
    periods = CompareRequest(student_id="student-01", baseline_start=date(2026, 10, 19),
                             baseline_end=date(2026, 10, 25), current_start=date(2026, 10, 26),
                             current_end=date(2026, 11, 1))
    compared = environment.client.post("/api/care/tag-comparison", content=periods.model_dump_json(),
                                       headers={"Content-Type": "application/json"})
    assert compared.status_code == 200
    result = TagComparison.model_validate_json(compared.content)
    summary = next(item for item in result.summaries if item.label == label)
    assert summary.current_count == 2 and summary.current_per_hour == 120
    assert summary.baseline_count is None and summary.count_difference is None
    assert any("不作疾病或情绪判断" in note for note in result.notes)
    for state in ("inattention", "sleeping"):
        assert next(item for item in result.summaries if item.label == state).current_count is None


@pytest.mark.parametrize("label", ["sneeze", "chair_movement", "door_close", "desk_tap", "pen_drop"])
def test_recorded_audible_event_cannot_be_declared_external_state(label: TagLabel):
    with pytest.raises(ValidationError, match="声音观测"):
        TagValue(tag_id="source-1", label=label, original_label="原始标注", category="external_state",
                 start_ms=3000, end_ms=4000, count=1)
