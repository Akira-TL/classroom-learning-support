"""渲染暂停期间的真实SQLite写事务串行化，不替换SQL或依赖定时等待。"""

import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, current_thread

import pytest
from roles.test_exports import Exports
from roles.test_exports import exports as exports
from test_evidence import environment as environment
from test_evidence import model_response as model_response
from test_exercises import control as control
from test_exercises import ready as ready
from test_plans import planning as planning

from teaching.classroom.storage import SQLiteStore
from teaching.exports.models import ExportMetadata, ExportSources
from teaching.exports.render import render_report
from teaching.exports.store import ExportStore
from teaching.learning.models import EvidenceReview
from teaching.learning.store import EvidenceStore
from teaching.plans.models import PlanReview
from teaching.plans.store import PlanStore


@pytest.mark.parametrize("revision_kind", ["evidence", "plan"])
def test_revision_during_render_serializes_and_old_download_never_revives(
    exports: Exports, monkeypatch: pytest.MonkeyPatch, revision_kind: str,
) -> None:
    env = exports.planning.ready.env
    reports, evidence, plans = ExportStore(env.store), EvidenceStore(env.store), PlanStore(env.store)
    rendering, release_render, writer_attempt, writer_committed = Event(), Event(), Event(), Event()
    commits: list[str] = []
    original_connection = SQLiteStore.connection

    @contextmanager
    def observe_real_transactions(store: SQLiteStore) -> Iterator[sqlite3.Connection]:
        with original_connection(store) as db:
            name = current_thread().name

            def trace(statement: str) -> None:
                # trace只观察正在真实执行的SQL，不改变连接、语句或返回值。
                if name.startswith("revision-writer") and statement == "BEGIN IMMEDIATE":
                    writer_attempt.set()
                if statement == "COMMIT":
                    if name.startswith("report-export"):
                        commits.append("export")
                    elif name.startswith("revision-writer"):
                        commits.append("revision")

            db.set_trace_callback(trace)
            yield db

    def paused_render(metadata: ExportMetadata, source: ExportSources) -> str:
        if not rendering.is_set():
            rendering.set()
            assert release_render.wait(10), "测试未释放报告渲染"
        return render_report(metadata, source)

    def revise() -> None:
        if revision_kind == "evidence":
            original = exports.planning.ready.evidence
            evidence.review(env.cid, "teacher-01", original.id, EvidenceReview(
                expected_revision=original.revision, action="confirmed",
                content=original.content.model_copy(update={"interpretation": "修订后的依据：先检查分块面积"}),
            ))
        else:
            plans.update(env.cid, "teacher-01", exports.plan.id, PlanReview(
                expected_revision=exports.plan.revision, action="confirmed",
                content=exports.plan.content.model_copy(update={"activity": "修订后的活动：比较各块面积"}),
            ))
        writer_committed.set()

    monkeypatch.setattr(SQLiteStore, "connection", observe_real_transactions)
    monkeypatch.setattr("teaching.exports.store.render_report", paused_render)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="report-export") as exporter:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="revision-writer") as reviser:
            exporting = exporter.submit(reports.create, env.cid, "teacher-01", exports.request())
            try:
                assert rendering.wait(5), "导出未到达渲染边界"
                assert list(reports.directory.iterdir()) == []
                revising = reviser.submit(revise)
                assert writer_attempt.wait(5), "修订线程未尝试真实写事务"
                assert not writer_committed.is_set() and not revising.done()
            finally:
                release_render.set()
            exported = exporting.result(timeout=10)
            revising.result(timeout=10)

    assert writer_committed.is_set() and commits == ["export", "revision"]
    assert exported.status == "active"
    directory = reports.directory
    original_file = directory / f"{exported.id}.html"
    original_html = original_file.read_text(encoding="utf-8")
    assert "教师确认需比较面积相等条件" in original_html
    assert "修订后的" not in original_html
    assert "</html>" in original_html and list(directory.glob("*.part")) == []
    assert len(list(directory.glob("*.html"))) == 1

    # 修订已经提交，此后读取和旧幂等请求都不能把快照恢复为可下载状态。
    download = f"/api/exports/{exported.id}/download"
    assert env.client.get(download).status_code == 410
    status = env.client.get(f"/api/exports/{exported.id}/status").json()
    assert status["status"] == "stale" and status["revision"] == 2
    repeated = exports.create()
    assert repeated.id == exported.id and repeated.status == "stale" and repeated.revision == 2
    assert env.client.get(download).status_code == 410
    assert original_file.read_text(encoding="utf-8") == original_html
    assert len(list(directory.glob("*.html"))) == 1 and list(directory.glob("*.part")) == []

    next_request = exports.request().model_copy(update={
        "idempotency_key": "export-after-concurrent-revision",
        "expected_plan_revision": exports.plan.revision + (revision_kind == "plan"),
    })
    response = env.client.post(exports.url, content=next_request.model_dump_json())
    if revision_kind == "plan":
        assert response.status_code == 200
        refreshed = ExportMetadata.model_validate_json(response.content)
        assert refreshed.id != exported.id
        current_html = env.client.get(f"/api/exports/{refreshed.id}/download")
        assert current_html.status_code == 200 and "修订后的活动：比较各块面积" in current_html.text
        assert env.client.get(download).status_code == 410
    else:
        assert response.status_code == 409
        assert len(list(directory.glob("*.html"))) == 1
    assert list(directory.glob("*.part")) == []
