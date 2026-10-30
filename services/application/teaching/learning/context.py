"""从当前持久记录构造教学依据，不接受客户端自报已确认。"""

import hashlib
import sqlite3

from pydantic import ValidationError

from ..audio.models import Utterance
from ..classroom.classrooms import Classroom
from ..classroom.storage import StoreError
from ..models import VerifiedContext
from .models import EvidenceBasis, GenerateEvidence


def build_basis(db: sqlite3.Connection, cid: str, teacher: str, request: GenerateEvidence) -> EvidenceBasis:
    row = db.execute("SELECT payload FROM classrooms WHERE id=?", (cid,)).fetchone()
    if not row:
        raise StoreError(404, "课堂不存在")
    classroom = Classroom.model_validate_json(row[0])
    if classroom.teacher_id != teacher:
        raise StoreError(403, "无权访问课堂")
    row = db.execute(
        "SELECT body FROM utterances WHERE classroom_id=? AND session_id=? AND segment_id=?",
        (cid, request.session_id, request.segment_id),
    ).fetchone()
    if not row:
        raise StoreError(404, "发言不存在")
    utterance = Utterance.model_validate_json(row[0])
    if utterance.phase not in {"final", "revision"} or (
        utterance.text_review,
        utterance.identity_review,
        utterance.question_review,
    ) != ("confirmed", "confirmed", "confirmed"):
        raise StoreError(409, "发言文字、身份和题目须分别核验")
    if utterance.student_alias not in classroom.students:
        raise StoreError(409, "发言学生不在当前课堂名单")
    question = next((item for item in classroom.questions if item.id == utterance.question_id), None)
    if question is None:
        raise StoreError(409, "发言题目不属于当前课堂")
    fingerprint = hashlib.sha256(question.model_dump_json().encode()).hexdigest()
    try:
        context = VerifiedContext(
            question_id=question.id,
            question_revision=int(fingerprint[:12], 16) + 1,
            objective=classroom.objective,
            question=question.text,
            reference_answer=question.reference_answer,
            diagram_required=question.diagram_required,
            diagram_description=question.diagram_description,
            utterance_id=utterance.segment_id,
            utterance_revision=utterance.version,
            student_alias=utterance.student_alias,
            utterance=utterance.teacher_text or utterance.upstream_text,
            text_confirmed=True,
            identity_confirmed=True,
            question_confirmed=True,
        )
    except ValidationError:
        raise StoreError(422, "教学上下文不足，请补充题目图形等必要内容") from None
    return EvidenceBasis(
        session_id=request.session_id,
        segment_id=request.segment_id,
        utterance_version=utterance.version,
        question_fingerprint=fingerprint,
        context=context,
    )
