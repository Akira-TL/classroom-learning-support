"""教师音轨代理只访问服务端配置的固定语音服务，不执行事件中的 URL。"""

import os
from urllib.parse import quote, urlsplit

import httpx
from fastapi import HTTPException, Response


def service_url() -> str:
    value = os.getenv("SPEECH_SERVICE_URL", "http://127.0.0.1:8765").rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(503, "语音服务地址须为本机 HTTP 服务")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise HTTPException(503, "语音服务地址只能包含协议、主机和端口")
    return value


def fetch_track(session_id: str, ref_id: str) -> Response:
    url = f"{service_url()}/v1/audio/{quote(session_id, safe='')}/ref/{quote(ref_id, safe='')}"
    try:
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", url) as upstream:
                if upstream.status_code != 200:
                    status = upstream.status_code if upstream.status_code in {404, 409} else 502
                    raise HTTPException(status, "音轨尚不可用" if status == 409 else "语音服务未提供该音轨")
                content = bytearray()
                for block in upstream.iter_bytes():
                    if len(content) + len(block) > 64 * 1024 * 1024:
                        raise HTTPException(413, "音轨超过单次读取限制")
                    content.extend(block)
    except httpx.HTTPError:
        raise HTTPException(502, "无法读取语音服务音轨") from None
    if bytes(content[:4]) != b"RIFF" or bytes(content[8:12]) != b"WAVE":
        raise HTTPException(502, "语音服务返回了非 WAV 音轨")
    return Response(bytes(content), media_type="audio/wav", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })
