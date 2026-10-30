"""仅汇总预置管理范围；有效性校验与计数使用同一事务快照。"""

from datetime import UTC, datetime

from ..classroom.storage import SQLiteStore, StoreError
from ..exercises.models import ExerciseRecord
from ..exercises.store import ExerciseStore
from ..learning.models import EvidenceRecord
from ..learning.store import EvidenceStore
from ..manual_exercises.models import ManualExerciseRecord
from ..manual_exercises.store import ManualExerciseStore
from ..plans.models import PlanRecord
from ..plans.store import PlanStore
from .counts import SupportCounts, ratio
from .models import AdminSummary, ManualMetrics, ResourceNeed

AUTHORIZED_TEACHER = "teacher-01"


class OverviewStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self.evidence = EvidenceStore(store)
        PlanStore(store)
        ExerciseStore(store)
        ManualExerciseStore(store)

    def summary(self) -> AdminSummary:
        evidence_count = observations = 0
        plans = SupportCounts()
        exercises = SupportCounts()
        manual_count = manual_confirmed = manual_adopted = 0
        students: set[str] = set()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            snapshot_at = datetime.now(UTC)
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
                    if plan.status == "stale":
                        continue
                    try:
                        self.evidence.require_confirmed(
                            db, cid, AUTHORIZED_TEACHER, plan.evidence_id, plan.evidence_revision
                        )
                    except StoreError:
                        continue
                    plans.generated += 1
                    if plan.status == "confirmed" and plan.content.complete():
                        plans.confirmed += 1
                        if plan.adopted:
                            plans.adopted += 1
                            observations += len(plan.observations)
                rows = db.execute("SELECT body FROM exercise_sets WHERE classroom_id=?", (cid,)).fetchall()
                for row in rows:
                    exercise = ExerciseRecord.model_validate_json(row[0])
                    if exercise.status == "stale":
                        continue
                    try:
                        self.evidence.require_confirmed(
                            db, cid, AUTHORIZED_TEACHER, exercise.evidence_id, exercise.evidence_revision
                        )
                    except StoreError:
                        continue
                    exercises.generated += 1
                    if exercise.status == "confirmed":
                        exercises.confirmed += 1
                        if exercise.adopted:
                            exercises.adopted += 1
                rows = db.execute("SELECT body FROM manual_exercise_sets WHERE classroom_id=?", (cid,)).fetchall()
                for row in rows:
                    manual = ManualExerciseRecord.model_validate_json(row[0])
                    manual_count += 1
                    if manual.status == "confirmed":
                        manual_confirmed += 1
                        if manual.adopted:
                            manual_adopted += 1
        state = "no_data" if not students else "hidden" if len(students) < 5 else "available"
        explanation = {
            "no_data": "尚无当前有效的已确认证据，未显示学生相关指标。",
            "hidden": "当前有效证据涉及的不同学生少于5名，学生相关指标已隐藏。",
            "available": "达到5名不同学生的演示阈值，仅显示整体数量，不提供个人或分组明细。",
        }[state]
        return AdminSummary(
            scope="固定演示授权：仅第一位教师的课堂；不包含其他教师的课堂，不接受范围筛选。",
            snapshot_at=snapshot_at,
            time_range="截至本次快照，当前仍保留的授权课堂状态；不按历史生成日期筛选，已删除课堂不计。",
            plan_metrics=plans.view(),
            exercise_metrics=exercises.view(),
            manual_exercise_metrics=ManualMetrics(
                recorded_count=manual_count,
                confirmed_count=manual_confirmed,
                adopted_count=manual_adopted,
                confirmation_rate=ratio(manual_confirmed, manual_count),
                adoption_rate=ratio(manual_adopted, manual_confirmed),
            ),
            classroom_count=len(classrooms),
            adopted_plan_count=plans.adopted,
            adopted_exercise_count=exercises.adopted,
            observation_count=observations,
            resource_needs=[
                ResourceNeed(
                    kind="exercise_materials",
                    description="准备已采用的证据驱动练习材料，每组计1项",
                    count=exercises.adopted,
                ),
                ResourceNeed(
                    kind="teaching_activities", description="准备已采用教学活动，每项安排计1项", count=plans.adopted
                ),
                ResourceNeed(
                    kind="manual_exercise_materials",
                    description="准备已采用人工通用练习材料，每组计1项",
                    count=manual_adopted,
                ),
            ],
            performance_state=state,
            confirmed_evidence_count=evidence_count if state == "available" else None,
            observed_student_count=len(students) if state == "available" else None,
            hidden=state == "hidden",
            explanation=explanation,
            counting_rule=(
                "课堂按授权课堂去重。有效生成按当前证据支持的成功结果记录去重，包含待核验和驳回记录；"
                "失败、处理中、过期返回及幂等重试不新增生成数。明确新建的成功任务是不同结果记录。"
                "确认率=当前已确认数/有效生成数，采用率=当前已采用数/当前已确认数，分母为0时未定义。"
                "撤销采用只减少采用数，依据失效使对应生成、确认和采用均不再计入当前有效口径。"
                "检查条数只计这些已采用安排的记录，撤销采用或依据失效后不计。"
                "人工通用练习单列录入、确认、采用，录入数是其确认率分母，不混入模型生成数。"
                "证据按记录去重、学生按不同身份去重，不按任务或事件重复计数。"
                "五人仅为已批准的演示规则，不是匿名化标准。资源需求是固定计数，不作模型判断。"
            ),
        )
