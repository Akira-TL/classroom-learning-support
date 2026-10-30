"""课堂、名单与题目上下文。"""

from datetime import date as CalendarDate
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEMO_STUDENTS = tuple(f"student-{number:02d}" for number in range(1, 11))


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=6000)
    reference_answer: str = Field(min_length=1, max_length=6000)
    diagram_required: bool = False
    diagram_description: str | None = Field(default=None, min_length=1, max_length=4000)


class ClassroomContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    date: CalendarDate
    objective: str = Field(min_length=1, max_length=2000)
    students: list[str] = Field(min_length=1, max_length=10)
    questions: list[Question] = Field(min_length=1, max_length=30)
    source: str = Field(min_length=1, max_length=1000)
    authorization: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        if len(set(self.students)) != len(self.students) or any(s not in DEMO_STUDENTS for s in self.students):
            raise ValueError("名单只能包含不重复的固定虚构学生 student-01 至 student-10")
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("题目标识不能重复")
        return self


class CreateClassroom(ClassroomContent):
    idempotency_key: str = Field(min_length=8, max_length=100)


class UpdateClassroom(ClassroomContent):
    expected_revision: int = Field(ge=1)


class Classroom(ClassroomContent):
    id: str
    teacher_id: str
    revision: int = Field(ge=1)
