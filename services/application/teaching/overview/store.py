"""仅汇总预置管理范围；有效性校验与计数使用同一事务快照。"""

from ..classroom.storage import SQLiteStore, StoreError
from ..exercises.models import ExerciseRecord
from ..exercises.store import ExerciseStore
from ..learning.models import EvidenceRecord
from ..learning.store import EvidenceStore
from ..plans.models import PlanRecord
from ..plans.store import PlanStore
from .models import AdminSummary, ResourceNeed

AUTHORIZED_TEACHER = "teacher-01"


class OverviewStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self.evidence = EvidenceStore(store)
        PlanStore(store)
        ExerciseStore(store)

    def summary(self) -> AdminSummary:
        evidence_count = plan_count = exercise_count = observations = 0
        students: set[str] = set()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            classrooms = db.execute("SELECT id FROM classrooms WHERE teacher_id=?", (AUTHORIZED_TEACHER,)).fetchall()
            for classroom in classrooms:
                cid = classroom[0]
                rows = db.execute("SELECT body FROM evidence_records WHERE classroom_id=?", (cid,)).fetchall()
                for row in rows:
                    record = EvidenceRecord.model_validate_json(row[0])
                    if record.status != "confirmed":
                        continue
                    try:
                        current = self.evidence.require_confirmed(
                            db, cid, AUTHORIZED_TEACHER, record.id, record.revision
                        )
                    except StoreError:
                        continue
                    evidence_count += 1
                    students.add(current.basis.context.student_alias)
                rows = db.execute("SELECT body FROM plan_records WHERE classroom_id=?", (cid,)).fetchall()
                for row in rows:
                    plan = PlanRecord.model_validate_json(row[0])
                    if plan.status != "confirmed" or not plan.adopted or not plan.content.complete():
                        continue
                    try:
                        self.evidence.require_confirmed(
                            db, cid, AUTHORIZED_TEACHER, plan.evidence_id, plan.evidence_revision
                        )
                    except StoreError:
                        continue
                    plan_count += 1
                    observations += len(plan.observations)
                rows = db.execute("SELECT body FROM exercise_sets WHERE classroom_id=?", (cid,)).fetchall()
                for row in rows:
                    exercise = ExerciseRecord.model_validate_json(row[0])
                    if exercise.status != "confirmed" or not exercise.adopted:
                        continue
                    try:
                        self.evidence.require_confirmed(
                            db, cid, AUTHORIZED_TEACHER, exercise.evidence_id, exercise.evidence_revision
                        )
                    except StoreError:
                        continue
                    exercise_count += 1
        state = "no_data" if not students else "hidden" if len(students) < 5 else "available"
        explanation = {
            "no_data": "尚无当前有效的已确认证据，未显示学生相关指标。",
            "hidden": "当前有效证据涉及的不同学生少于5名，学生相关指标已隐藏。",
            "available": "达到5名不同学生的演示阈值，仅显示整体数量，不提供个人或分组明细。",
        }[state]
        return AdminSummary(
            scope="固定演示授权：仅第一位教师的课堂；不包含其他教师的课堂，不接受范围筛选。",
            classroom_count=len(classrooms),
            adopted_plan_count=plan_count,
            adopted_exercise_count=exercise_count,
            observation_count=observations,
            resource_needs=[
                ResourceNeed(
                    kind="exercise_materials", description="准备已采用练习材料，每组计1项", count=exercise_count
                ),
                ResourceNeed(
                    kind="teaching_activities", description="准备已采用教学活动，每项安排计1项", count=plan_count
                ),
            ],
            performance_state=state,
            confirmed_evidence_count=evidence_count if state == "available" else None,
            observed_student_count=len(students) if state == "available" else None,
            hidden=state == "hidden",
            explanation=explanation,
            counting_rule=(
                "课堂按授权课堂去重；教学安排与练习只计当前有效证据支持、已确认且已采用的记录。"
                "检查条数只计这些已采用安排的记录，撤销采用或依据失效后不计。"
                "证据按记录去重、学生按不同身份去重，不按任务或事件重复计数。"
                "五人仅为已批准的演示规则，不是匿名化标准。资源需求是固定计数，不作模型判断。"
            ),
        )
