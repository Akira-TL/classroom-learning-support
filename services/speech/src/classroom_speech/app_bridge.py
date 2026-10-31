"""转换桥：把语音服务的 speech.v0.1 事件转成教学应用当前接受的 app-draft-1，并推送到应用的可信接入入口。

应用侧接口（见 docs/handoff/语音接口当前支持范围.md）：
    POST {APP}/api/integrations/speech/events
    Authorization: Bearer <SPEECH_INGEST_TOKEN>
    {"classroom_id": ..., "event": {app-draft-1 字段}}

app-draft-1 不接受多余字段，也没有位置、音频引用和可靠性状态。转换规则：

| speech.v0.1 | app-draft-1 |
|---|---|
| transcript.partial / final / revised（有 text） | partial / final / revision |
| transcript.retracted | withdraw |
| transcript.final 无 text（ASR 不可用 / 未识别） | 不发送：应用要求转写事件带文字，也没有“无法识别”状态 |
| source.position | 不发送；其中的匿名说话人标签填进同一片段转写事件的 source_ref |
| audio.available | 不发送（应用的原音频走教师授权上传，另行交接） |
| stream.status gap | status=disconnected + gap_start_ms / gap_end_ms |
| session.ended | status=ended，随后 end（end 封闭会话，最终修订须已送达） |

丢掉的信息（reliability_state、方位、overlap.with、audio_ref、diagnostics 里的数学守卫核验原因）
逐条记在 BridgeReport.dropped，便于和应用方确认协议扩展；不把它们塞进 source_ref 字符串冒充已支持。

来源：live / file_replay → upstream_live（音频经真实语音服务实时处理）；回放已保存的事件 → recorded_result；
simulated 或测试替身引擎（oracle_*）→ synthetic，应用的可信入口会拒收，桥在本地就拒绝发送。
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .events import EventType, SpeechEvent

log = logging.getLogger(__name__)

APP_PROTOCOL = "app-draft-1"
APP_EVENT_KEYS = {
    "protocol_version", "session_id", "event_id", "sequence", "event_type", "source_kind", "segment_id", "revision",
    "start_ms", "end_ms", "text", "source_ref", "overlap", "status", "gap_start_ms", "gap_end_ms",
}
_TRANSCRIPT = {
    EventType.TRANSCRIPT_PARTIAL: "partial",
    EventType.TRANSCRIPT_FINAL: "final",
    EventType.TRANSCRIPT_REVISED: "revision",
}
_ORIGIN = {"live": "upstream_live", "file_replay": "upstream_live", "simulated": "synthetic"}


class SyntheticRefused(ValueError):
    """模拟数据不能送进应用的可信接入入口。"""


@dataclass
class BridgeReport:
    sent: int = 0
    duplicates: int = 0
    dropped: list[dict] = field(default_factory=list)  # 未发送的事件或被丢弃的字段，带原因
    errors: list[dict] = field(default_factory=list)


class AppEventMapper:
    """有状态的逐事件转换：记住每个片段的匿名说话人标签。同一会话用同一个实例。"""

    def __init__(self, source_kind: str | None = None) -> None:
        self.source_kind = source_kind  # None 表示按事件的 data_origin 推断
        self.labels: dict[str, str] = {}
        self.report = BridgeReport()

    def _kind(self, ev: SpeechEvent) -> str:
        engine = (ev.diagnostics or {}).get("engine", "")
        if ev.data_origin == "simulated" or engine.startswith("oracle"):
            return "synthetic"  # 指定 source_kind 也不能把模拟数据改标成真实结果
        return self.source_kind or _ORIGIN[ev.data_origin]

    def _drop(self, ev: SpeechEvent, reason: str, fields: list[str] | None = None) -> None:
        self.report.dropped.append({"event_id": ev.event_id, "event_type": ev.event_type.value, "segment_id": ev.segment_id,
                                    "reason": reason, **({"fields": fields} if fields else {})})

    def _base(self, ev: SpeechEvent, event_type: str, event_id: str | None = None) -> dict:
        kind = self._kind(ev)
        if kind == "synthetic":
            raise SyntheticRefused(f"{ev.event_id} 来自模拟数据或测试替身，不能写入应用可信入口；请用教师模拟入口")
        return {"protocol_version": APP_PROTOCOL, "session_id": ev.session_id, "event_id": event_id or ev.event_id,
                "sequence": ev.sequence, "event_type": event_type, "source_kind": kind}

    def map(self, ev: SpeechEvent) -> list[dict]:
        """返回 0–2 条 app-draft-1 事件（不含外层 classroom_id）。"""
        t = ev.event_type
        if t == EventType.SOURCE_POSITION:
            for rec in ev.sources:
                if rec.kind == "anon_speaker" and ev.segment_id:
                    self.labels[ev.segment_id] = str(rec.value)
            self._drop(ev, "app-draft-1 没有位置事件；匿名标签并入转写事件的 source_ref", ["azimuth", "rebind_hint"])
            return []
        if t == EventType.AUDIO_AVAILABLE:
            self._drop(ev, "app-draft-1 没有音频可用事件；原音频须按应用的教师授权通道另行交接")
            return []
        if t in _TRANSCRIPT or t == EventType.TRANSCRIPT_RETRACTED:
            if t != EventType.TRANSCRIPT_RETRACTED and not ev.text:
                self._drop(ev, f"无转写文字（{ev.status}）：app-draft-1 的转写事件必须带文字，也没有“无法识别”状态")
                return []
            out = self._base(ev, _TRANSCRIPT.get(t, "withdraw"))
            out.update(segment_id=ev.segment_id, revision=ev.revision or 1, start_ms=ev.start_ms or 0, end_ms=ev.end_ms or 0,
                       overlap=bool(ev.overlap and ev.overlap.present))
            if ev.text:
                out["text"] = ev.text
            if ev.segment_id in self.labels:
                out["source_ref"] = self.labels[ev.segment_id]
            lost = [k for k in ("reliability_state", "audio_ref", "diagnostics", "replaces") if getattr(ev, k)]
            if ev.overlap and ev.overlap.with_segments:
                lost.append("overlap.with")
            if lost:
                self._drop(ev, "app-draft-1 不接受这些字段，已丢弃", lost)
            return [out]
        if t == EventType.STREAM_STATUS:
            if ev.status == "gap" and ev.gap:
                out = self._base(ev, "status")
                out.update(status="disconnected", start_ms=ev.gap.start_ms, end_ms=ev.gap.end_ms,
                           gap_start_ms=ev.gap.start_ms, gap_end_ms=ev.gap.end_ms)
                return [out]
            if ev.status == "resumed":
                out = self._base(ev, "status")
                out.update(status="running", start_ms=ev.start_ms or 0, end_ms=ev.end_ms or ev.start_ms or 0)
                return [out]
            self._drop(ev, f"app-draft-1 没有对应状态：{ev.status}")
            return []
        if t == EventType.SESSION_ENDED:
            ended = self._base(ev, "status", f"{ev.event_id}_status")
            ended.update(status="ended", start_ms=ev.start_ms or 0, end_ms=ev.end_ms or 0)
            end = self._base(ev, "end")
            end.update(start_ms=ev.start_ms or 0, end_ms=ev.end_ms or 0)
            if ev.status not in (None, "completed"):
                self._drop(ev, f"会话结束状态 {ev.status} 在 app-draft-1 里无法区分", ["status"])
            return [ended, end]
        self._drop(ev, f"未知事件类型 {t}")
        return []


class AppClient:
    """向应用可信入口推送。网络错误与 5xx 按指数退避重试同一请求（应用按事件标识幂等）。"""

    def __init__(self, base_url: str, token: str, classroom_id: str, retries: int = 4, timeout_s: float = 10.0) -> None:
        if len(token.strip()) < 32:
            raise ValueError("SPEECH_INGEST_TOKEN 不足 32 字符，应用会拒绝")
        self.url = base_url.rstrip("/") + "/api/integrations/speech/events"
        self.token, self.classroom_id, self.retries, self.timeout = token.strip(), classroom_id, retries, timeout_s

    def post(self, event: dict) -> tuple[int, dict]:
        assert set(event) <= APP_EVENT_KEYS, set(event) - APP_EVENT_KEYS
        body = json.dumps({"classroom_id": self.classroom_id, "event": event}, ensure_ascii=False).encode()
        req = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        delay = 2.0
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.status, json.loads(resp.read() or b"{}")
            except urllib.error.HTTPError as err:
                detail = json.loads(err.read() or b"{}") if err.headers.get("content-type", "").startswith("application/json") else {}
                if err.code < 500 or attempt == self.retries:
                    return err.code, detail
            except (urllib.error.URLError, TimeoutError) as err:
                if attempt == self.retries:
                    return 0, {"detail": str(err)}
            time.sleep(delay)
            delay *= 2
        return 0, {}


def push_events(events, mapper: AppEventMapper, client: AppClient) -> BridgeReport:
    """按顺序转换并推送一批事件。遇到 401/404/409/410/422 停止：继续发只会让应用状态更乱。"""
    for ev in events:
        for app_ev in mapper.map(ev):
            code, body = client.post(app_ev)
            if code == 200:
                if body.get("created"):
                    mapper.report.sent += 1
                else:
                    mapper.report.duplicates += 1
                continue
            mapper.report.errors.append({"event_id": app_ev["event_id"], "status": code, "detail": body.get("detail")})
            return mapper.report
    return mapper.report


class AppForwarder:
    """挂到 Session.listeners 上实时转发。推送在后台线程里做，不阻塞音频处理。"""

    def __init__(self, client: AppClient, source_kind: str | None = None) -> None:
        self.client, self.mapper = client, AppEventMapper(source_kind)
        self._q: queue.Queue = queue.Queue()
        self._stopped = False
        threading.Thread(target=self._run, daemon=True).start()

    def __call__(self, ev: SpeechEvent) -> None:
        self._q.put(ev)

    def _run(self) -> None:
        while True:
            ev = self._q.get()
            if self._stopped:
                continue
            try:
                push_events([ev], self.mapper, self.client)
            except SyntheticRefused as exc:
                self.mapper.report.errors.append({"event_id": ev.event_id, "status": "refused", "detail": str(exc)})
            if self.mapper.report.errors:
                self._stopped = True
                log.error("应用接入停止：%s", self.mapper.report.errors[-1])
