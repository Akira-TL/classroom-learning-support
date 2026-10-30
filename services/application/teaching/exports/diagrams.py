"""仅对已核验的固定描述绘制确定性示意；不推测任意图片。"""

from dataclasses import dataclass
from html import escape

from ..models import VerifiedContext


@dataclass(frozen=True)
class Diagram:
    description: str
    widths: tuple[int, int, int, int]


DIAGRAMS = (
    Diagram("四块面积分别占整体的二分之一、四分之一、八分之一、八分之一。", (4, 2, 1, 1)),
    Diagram("四块面积分别占整体的四分之一、四分之一、四分之一、四分之一。", (1, 1, 1, 1)),
)


def question_diagram(context: VerifiedContext) -> str:
    if not context.diagram_required and context.diagram_description is None:
        return ""
    description = context.diagram_description or "未提供图形说明"
    section = f"<section><h2>教师核验的图形面积说明</h2><p>{escape(description)}</p>"
    matched = next((item for item in DIAGRAMS if item.description == description), None)
    if not context.diagram_required or matched is None:
        return section + "<p>没有对应的固定示意模板，未根据自定义说明猜测绘图。</p></section>"
    total = sum(matched.widths)
    shapes: list[str] = []
    left = 20
    for label, weight in zip(("甲", "乙", "丙", "丁"), matched.widths, strict=True):
        width = 600 * weight // total
        shapes.append(
            f'<rect x="{left}" y="25" width="{width}" height="100" fill="white" stroke="black" stroke-width="2"/>'
            f'<text x="{left + width / 2:g}" y="82" text-anchor="middle" fill="black" font-size="20">{label}</text>'
        )
        left += width
    return (
        section + '<figure><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 160" '
        'width="640" style="max-width:100%;height:auto" role="img" aria-label="按教师核验说明绘制的长方形四块示意">'
        f"<title>{escape(context.question_id)}：长方形四块示意</title><desc>{escape(description)}</desc>"
        + "".join(shapes)
        + "</svg><figcaption>按教师核验说明绘制的示意，非原始课堂图片；各块高度相等，面积比由宽度比确定。</figcaption>"
        "</figure></section>"
    )
