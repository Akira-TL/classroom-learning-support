from datetime import UTC, datetime
from html import escape
from html.parser import HTMLParser

import pytest
from roles.test_exports import Exports
from roles.test_exports import exports as exports
from test_evidence import environment as environment
from test_evidence import model_response as model_response
from test_exercises import control as control
from test_exercises import ready as ready
from test_plans import planning as planning

from teaching.exports.models import ExportMetadata, ExportSources
from teaching.exports.render import render_report


class RectangleWidths(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.widths: list[int] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "rect":
            width = next((value for name, value in attrs if name == "width"), None)
            if width is not None:
                self.widths.append(int(width))


def rendered(exports: Exports, description: str | None, required: bool = True) -> str:
    env = exports.planning.ready.env
    evidence = exports.planning.ready.evidence
    context = evidence.basis.context.model_copy(
        update={
            "question": "观察图中的四块，每块都一定是四分之一吗？",
            "reference_answer": "只有面积相等时每块都成立；不等分中仍可能有一块恰好占四分之一。",
            "diagram_required": required,
            "diagram_description": description,
        }
    )
    evidence = evidence.model_copy(update={"basis": evidence.basis.model_copy(update={"context": context})})
    source = ExportSources(
        classroom=env.store.get_classroom("teacher-01", env.cid),
        evidence=evidence,
        plan=exports.plan,
    )
    return render_report(
        ExportMetadata(
            id="render-check",
            revision=1,
            created_at=datetime(2026, 10, 31, tzinfo=UTC),
            status="active",
        ),
        source,
    )


@pytest.mark.parametrize(
    "description,widths",
    [
        ("四块面积分别占整体的二分之一、四分之一、八分之一、八分之一。", [300, 150, 75, 75]),
        ("四块面积分别占整体的四分之一、四分之一、四分之一、四分之一。", [150, 150, 150, 150]),
    ],
)
def test_known_area_diagram_is_self_contained_and_complete(
    exports: Exports, description: str, widths: list[int]
) -> None:
    html = rendered(exports, description)
    assert "观察图中的四块，每块都一定是四分之一吗？" in html
    assert "只有面积相等时每块都成立" in html
    assert description in html
    assert "非原始课堂图片" in html
    assert exports.planning.ready.evidence.content.follow_up_question in html
    assert "参考答案" in html and "题目标识" in html
    assert "<svg" in html
    parser = RectangleWidths()
    parser.feed(html)
    assert parser.widths == widths
    assert "<script" not in html
    assert '<img src="http' not in html


def test_unknown_description_is_preserved_and_escaped_without_guessing(exports: Exports) -> None:
    description = '<svg onload="alert(1)">没有提供面积比例的自定义形状</svg>'
    html = rendered(exports, description)
    assert escape(description) in html
    assert "没有对应的固定示意模板" in html
    assert "<svg" not in html
    assert "<script" not in html


def test_text_only_question_does_not_invent_figure(exports: Exports) -> None:
    html = rendered(exports, None, False)
    assert "参考答案" in html
    assert "<svg" not in html
    assert "教师核验的图形面积说明" not in html
