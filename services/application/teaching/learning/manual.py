"""教师人工初稿与云端生成共享依据、确认及失效规则。"""

from typing import TYPE_CHECKING
from uuid import uuid4

from ..audio.store import require_classroom
from ..classroom.storage import StoreError
from ..models import EvidenceDraft
from .context import build_basis
from .models import EvidenceRecord, EvidenceTask, GenerateEvidence, GenerationResult, ManualEvidenceRequest

if TYPE_CHECKING:
    from .store import EvidenceStore


def save_manual(store: "EvidenceStore", cid: str, teacher: str, request: ManualEvidenceRequest) -> GenerationResult:
    store.store.get_classroom(teacher, cid)
    base = GenerateEvidence.model_validate(request.model_dump(exclude={"content"}))
    with store.store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        require_classroom(db, cid)
        row = db.execute(
            "SELECT body FROM evidence_tasks WHERE classroom_id=? AND request_key=?", (cid, base.idempotency_key)
        ).fetchone()
        if row:
            task = EvidenceTask.model_validate_json(row[0])
            if task.origin != "teacher_manual" or task.request != base or task.manual_content != request.content:
                raise StoreError(409, "相同幂等标识不能用于不同来源或内容的证据请求")
            return store._refresh(db, task, teacher)
        basis = build_basis(db, cid, teacher, base)
        if basis.utterance_version != base.expected_version:
            raise StoreError(409, "发言版本已变化，请重新读取")
        if request.content.quote != basis.context.utterance:
            raise StoreError(422, "人工证据引用必须逐字等于当前已核验原话")
        draft = EvidenceDraft(context=basis.context, content=request.content, model="teacher_manual")
        task = EvidenceTask(
            id=uuid4().hex,
            classroom_id=cid,
            request=base,
            basis=basis,
            status="succeeded",
            origin="teacher_manual",
            manual_content=request.content,
        )
        record = EvidenceRecord(
            id=uuid4().hex,
            task_id=task.id,
            classroom_id=cid,
            basis=basis,
            original=draft,
            content=request.content,
        )
        db.execute(
            "INSERT INTO evidence_tasks VALUES (?, ?, ?, ?)",
            (
                task.id,
                cid,
                base.idempotency_key,
                task.model_dump_json(),
            ),
        )
        db.execute(
            "INSERT INTO evidence_records VALUES (?, ?, ?, ?)",
            (
                record.id,
                cid,
                task.id,
                record.model_dump_json(),
            ),
        )
        return GenerationResult(task=task, evidence=record)
