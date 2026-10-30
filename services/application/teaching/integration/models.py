from typing import Literal

from pydantic import Field

from ..audio.models import SpeechEvent
from ..models import StrictModel


class SpeechIngest(StrictModel):
    classroom_id: str = Field(min_length=1, max_length=80)
    event: SpeechEvent


class SpeechReceipt(StrictModel):
    created: bool


class SpeechEndpointStatus(StrictModel):
    endpoint_enabled: bool
    protocol_version: Literal["app-draft-1"] = "app-draft-1"
    message: str
