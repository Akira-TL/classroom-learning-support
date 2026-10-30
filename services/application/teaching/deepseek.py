"""直接调用 DeepSeek；不提供其他供应商或静默模拟回退。"""

import os
from typing import Literal, TypeVar

import httpx
from pydantic import BaseModel, Field, ValidationError

from .models import (
    ConfirmedEvidence,
    EvidenceContent,
    EvidenceDraft,
    SupportContent,
    SupportDraft,
    VerifiedContext,
)
from .prompts import EVIDENCE_PROMPT, SUPPORT_PROMPT

Result = TypeVar("Result", bound=BaseModel)


class GenerationError(RuntimeError):
    """只包含可公开的失败信息，不包含密钥、请求头或供应方原始响应。"""


class Message(BaseModel):
    role: Literal["system", "user"]
    content: str


class JsonFormat(BaseModel):
    type: Literal["json_object"] = "json_object"


class Thinking(BaseModel):
    type: Literal["disabled"] = "disabled"


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    response_format: JsonFormat = Field(default_factory=JsonFormat)
    thinking: Thinking = Field(default_factory=Thinking)
    stream: Literal[False] = False
    max_tokens: int = 2500


class ReplyMessage(BaseModel):
    content: str | None = None


class Choice(BaseModel):
    message: ReplyMessage
    finish_reason: str


class ChatReply(BaseModel):
    choices: list[Choice] = Field(min_length=1)


class DeepSeek:
    def __init__(self, client: httpx.Client, api_key: str, model: str = "deepseek-flash") -> None:
        if not api_key.strip():
            raise GenerationError("未配置 DEEPSEEK_API_KEY")
        self._client = client
        self._api_key = api_key.strip()
        self.model = model

    @classmethod
    def from_environment(cls, client: httpx.Client) -> "DeepSeek":
        return cls(client, os.getenv("DEEPSEEK_API_KEY", ""), os.getenv("DEEPSEEK_MODEL", "deepseek-flash"))

    def _generate(self, prompt: str, content: str, result_type: type[Result]) -> Result:
        request = ChatRequest(
            model=self.model,
            messages=[Message(role="system", content=prompt), Message(role="user", content=content)],
        )
        try:
            response = self._client.post(
                "https://api.deepseek.com/chat/completions",
                content=request.model_dump_json(),
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                timeout=httpx.Timeout(60, connect=10),
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            raise GenerationError("DeepSeek 请求超时，请重试") from None
        except httpx.HTTPError:
            raise GenerationError("DeepSeek 网络请求失败，请检查连接") from None
        if response.status_code != 200:
            raise GenerationError(f"DeepSeek 请求失败（HTTP {response.status_code}），未生成有效结果")
        try:
            reply = ChatReply.model_validate_json(response.content).choices[0]
            if reply.finish_reason != "stop":
                raise GenerationError("DeepSeek 输出未完整结束，未保存为有效结果")
            if not reply.message.content or not reply.message.content.strip():
                raise GenerationError("DeepSeek 返回空内容，请重试")
            return result_type.model_validate_json(reply.message.content)
        except ValidationError:
            raise GenerationError("DeepSeek 输出不符合教学数据格式，请重试") from None

    def analyze(self, context: VerifiedContext) -> EvidenceDraft:
        content = self._generate(EVIDENCE_PROMPT, context.model_dump_json(), EvidenceContent)
        if content.quote != context.utterance:
            raise GenerationError("DeepSeek 引用与原话不一致，需重新生成")
        return EvidenceDraft(context=context, content=content, model=self.model)

    def support(self, evidence: ConfirmedEvidence) -> SupportDraft:
        content = self._generate(SUPPORT_PROMPT, evidence.model_dump_json(), SupportContent)
        return SupportDraft(evidence=evidence, content=content, model=self.model)
