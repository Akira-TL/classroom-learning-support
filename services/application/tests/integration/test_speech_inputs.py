"""真实服务转发协议的应用消费测试；不声明模型质量已验证。"""

import base64
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from test_speech_api import classroom_api as classroom_api

from teaching.classroom.storage import StoreError
from teaching.inputs import upstream
from teaching.inputs.models import InputSession


@pytest.mark.parametrize("channels", [1, 2])
def test_native_input_preserves_channels_and_retries_once(classroom_api: tuple[TestClient, str], channels: int):
    client, speech_url = classroom_api
    cid = speech_url.split("/")[-2]
    url = f"/api/classrooms/{cid}/input-sessions"
    with patch("teaching.inputs.upstream.create", return_value="ses_real") as create:
        response = client.post(url, json={
            "input_mode": "file_stream", "processing_mode": "speech_stream",
            "sample_rate": 16000, "channels": channels, "encoding": "pcm_s16le",
        })
    session = InputSession.model_validate_json(response.content)
    assert session.speech_session_id == "ses_real" and session.recognizer_connected
    assert create.call_args.args[0].channels == channels
    payload = {
        "sequence": 0, "start_sample": 0, "frame_count": 1600,
        "pcm_base64": base64.b64encode(b"\x01\x00" * 1600 * channels).decode(),
    }
    with patch("teaching.inputs.upstream.frame") as forward:
        assert client.post(f"{url}/{session.id}/frames", json=payload).status_code == 200
        assert client.post(f"{url}/{session.id}/frames", json=payload).status_code == 200
    assert forward.call_count == 1
    with patch("teaching.inputs.upstream.finish") as end, patch(
        "teaching.inputs.upstream.forwarding", return_value=True,
    ):
        completed = client.post(f"{url}/{session.id}/finish", json={})
    result = InputSession.model_validate_json(completed.content)
    assert result.status == "ended" and result.forwarding_pending
    assert result.audio_asset and result.audio_asset.channels == channels
    assert result.audio_asset.source == "file_stream_speech_stream"
    assert end.call_count == 1
    with patch("teaching.inputs.upstream.forwarding", return_value=False):
        assert not client.get(f"{url}/{session.id}").json()["forwarding_pending"]


def test_unconfirmed_upstream_frame_does_not_advance_cursor(classroom_api: tuple[TestClient, str]):
    client, speech_url = classroom_api
    url = f"/api/classrooms/{speech_url.split('/')[-2]}/input-sessions"
    with patch("teaching.inputs.upstream.create", return_value="ses_real"):
        response = client.post(url, json={
            "input_mode": "microphone", "processing_mode": "speech_stream",
            "sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le",
        })
    sid = response.json()["id"]
    payload = {"sequence": 0, "start_sample": 0, "frame_count": 1, "pcm_base64": "AAA="}
    with patch("teaching.inputs.upstream.frame", side_effect=StoreError(503, "未确认")):
        assert client.post(f"{url}/{sid}/frames", json=payload).status_code == 503
    assert client.get(f"{url}/{sid}").json()["received_samples"] == 0
    with patch("teaching.inputs.upstream.frame"):
        assert client.post(f"{url}/{sid}/frames", json=payload).status_code == 200


def test_upstream_requires_real_engine_and_forwarding_before_claiming_connection():
    session = InputSession(
        id="local", classroom_id="class", input_mode="microphone", sample_rate=16000,
        channels=1, encoding="pcm_s16le", processing_mode="speech_stream",
    )
    with patch("teaching.inputs.upstream.request", return_value=httpx.Response(
        200, json={"session_id": "ses_actual", "app_forwarding": True, "recognizer_connected": False},
    )):
        with pytest.raises(StoreError, match="真实识别引擎"):
            upstream.create(session)
    with patch("teaching.inputs.upstream.request", return_value=httpx.Response(
        200, json={"session_id": "ses_actual", "app_forwarding": True, "recognizer_connected": True},
    )) as request:
        assert upstream.create(session) == "ses_actual"
        body = upstream.SessionRequest.model_validate_json(request.call_args.args[2])
        assert body.app_classroom_id == "class" and body.data_origin == "live"
        assert body.sample_rate == 16000 and body.channels == 1
