"""原生事件无损归档，并映射为应用已存在的核验状态机。"""

from ..audio.models import SpeechEvent
from .native_models import NativeSpeechEvent

TYPES = {
    "transcript.partial": "partial", "transcript.final": "final", "transcript.revised": "revision",
    "transcript.retracted": "withdraw", "source.position": "metadata", "audio.available": "metadata",
    "stream.status": "metadata", "session.ended": "end",
}


def normalize(event: NativeSpeechEvent) -> SpeechEvent:
    engine = (event.diagnostics or {}).get("engine")
    if event.data_origin == "simulated" or isinstance(engine, str) and engine.startswith("oracle"):
        raise ValueError("模拟数据或脚本转写不能进入可信入口")
    status = {"resumed": "running", "gap": "disconnected"}.get(event.status or "") if (
        event.event_type == "stream.status"
    ) else None
    kind = "status" if status else TYPES[event.event_type]
    if event.event_type == "session.ended":
        status = "ended"
    return SpeechEvent.model_validate({
        "session_id": event.session_id, "event_id": event.event_id, "sequence": event.sequence,
        "event_type": kind, "source_kind": "upstream_live", "native_event": event,
        "segment_id": event.segment_id, "revision": event.revision or 1,
        "start_ms": event.start_ms or 0, "end_ms": event.end_ms or event.start_ms or 0,
        "text": event.text or None, "overlap": bool(event.overlap and event.overlap.present),
        "source_ref": next((str(s.value) for s in event.sources if s.kind == "anon_speaker"), None),
        "status": status, "gap_start_ms": event.gap.start_ms if event.gap else None,
        "gap_end_ms": event.gap.end_ms if event.gap else None,
    })
