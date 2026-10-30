from typing import Literal

from pydantic import Field, field_validator

from ..models import Exercise, StrictModel


def check_levels(items: list[Exercise]) -> list[Exercise]:
    if len(items) != 3 or {item.level for item in items} != {"concept", "explanation", "transfer"}:
        raise ValueError("三道练习须分别覆盖概念巩固、解释表达、情境迁移")
    return items


class CreateManualExercises(StrictModel):
    exercises: list[Exercise] = Field(min_length=3, max_length=3)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @field_validator("exercises")
    @classmethod
    def valid_levels(cls, items: list[Exercise]) -> list[Exercise]:
        return check_levels(items)


class ManualExerciseRecord(StrictModel):
    id: str
    classroom_id: str
    origin: Literal["teacher_manual_general"] = "teacher_manual_general"
    initial_exercises: list[Exercise]
    exercises: list[Exercise]
    created_by: str
    reviewed_by: str | None = None
    revision: int = 1
    status: Literal["pending", "confirmed", "rejected"] = "pending"
    adopted: bool = False
    adopted_by: str | None = None


class ManualReview(StrictModel):
    expected_revision: int = Field(ge=1)
    action: Literal["confirmed", "rejected"]
    exercises: list[Exercise] | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("exercises")
    @classmethod
    def valid_levels(cls, items: list[Exercise] | None) -> list[Exercise] | None:
        return check_levels(items) if items is not None else None


class ManualAdoption(StrictModel):
    expected_revision: int = Field(ge=1)
    adopted: bool


class ManualHistory(StrictModel):
    actor: str
    action: Literal["created", "confirmed", "rejected", "adopted", "unadopted"]
    record: ManualExerciseRecord
