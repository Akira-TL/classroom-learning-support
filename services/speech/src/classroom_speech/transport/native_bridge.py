"""原样推送 speech.v0.1；保留事件标识、来源及所有处理线索。"""

from __future__ import annotations

import queue
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from ..events import SpeechEvent


class Envelope(BaseModel):
    classroom_id: str
    event: SpeechEvent


class Receipt(BaseModel):
    created: bool


@dataclass
class ForwardingReport:
    sent: int = 0
    duplicates: int = 0
    pending: int = 0
    stopped: bool = False
    error: str | None = None
    event_id: str | None = None
    not_forwarded: list[str] = field(default_factory=list)


def require_real(event: SpeechEvent) -> None:
    engine = (event.diagnostics or {}).get("engine", "")
    if event.data_origin == "simulated" or str(engine).startswith("oracle"):
        raise ValueError("模拟数据和脚本转写不能进入可信语音入口")


class NativeClient:
    def __init__(self, base_url: str, token: str, classroom_id: str, timeout: float = 15) -> None:
        if len(token.strip()) < 32:
            raise ValueError("语音接入凭证至少32字符")
        self.url = base_url.rstrip("/") + "/api/integrations/speech/native-events"
        self.token, self.classroom_id, self.timeout = token.strip(), classroom_id, timeout

    def post(self, event: SpeechEvent) -> bool:
        require_real(event)
        body = Envelope(classroom_id=self.classroom_id, event=event).model_dump_json(by_alias=True).encode()
        request = urllib.request.Request(
            self.url, data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.token},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return Receipt.model_validate_json(response.read()).created


class NativeForwarder:
    """单消费者保序。失败事件留在队首；重试仍使用同一内容与事件标识。"""

    def __init__(self, client: NativeClient) -> None:
        self.client = client
        self.report = ForwardingReport()
        self._report_lock = threading.Lock()
        self._queue: queue.Queue[SpeechEvent] = queue.Queue()
        self._resume = threading.Event()
        self._resume.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def __call__(self, event: SpeechEvent) -> None:
        with self._report_lock:
            self.report.pending += 1
        self._queue.put(event)

    def retry(self) -> None:
        self.report.stopped = False
        self._resume.set()

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            delay = 1.0
            while True:
                self._resume.wait()
                try:
                    created = self.client.post(event)
                except urllib.error.HTTPError as error:
                    # 不记录响应体，避免把原始语音或凭证写入状态接口。
                    self.report.error = f"应用接入返回 HTTP {error.code}"
                    error.close()
                    retryable = error.code >= 500 or error.code == 429
                except (urllib.error.URLError, TimeoutError, OSError):
                    self.report.error = "应用接入网络中断"
                    retryable = True
                except (ValueError, ValidationError):
                    self.report.error = "事件来源或接入响应不符合契约"
                    retryable = False
                else:
                    self.report.sent += int(created)
                    self.report.duplicates += int(not created)
                    with self._report_lock:
                        self.report.pending -= 1
                    self.report.error = None
                    self.report.event_id = None
                    self.report.stopped = False
                    break
                self.report.event_id = event.event_id
                if retryable:
                    threading.Event().wait(delay)
                    delay = min(delay * 2, 30.0)
                else:
                    self.report.stopped = True
                    self._resume.clear()
            self._queue.task_done()
            if event.event_type == "session.ended":
                return
