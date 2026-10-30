from html import escape

from .diagrams import question_diagram
from .models import ExportMetadata, ExportSources


def section(title: str, value: str) -> str:
    return f"<section><h2>{escape(title)}</h2><p>{escape(value)}</p></section>"


def render_report(metadata: ExportMetadata, source: ExportSources) -> str:
    plan = source.plan
    content = plan.content
    context = source.evidence.basis.context
    parts = [
        section("课堂与教学目标", f"{source.classroom.title} · {source.classroom.date}\n{source.classroom.objective}"),
        section(
            "教师核验的题目与参考答案",
            f"题目标识：{context.question_id}\n题干：{context.question}\n参考答案：{context.reference_answer}",
        ),
        question_diagram(context),
        section("已确认的证据引用", f"学生：{content.target_student}\n原话：{context.utterance}"),
        section(
            "教师核验的学习证据",
            f"{source.evidence.content.interpretation}\n局限：{source.evidence.content.limitation}",
        ),
        section("证据跟进问题", source.evidence.content.follow_up_question),
        section(
            "提问安排",
            f"对象：{content.target_student}\n提问：{content.question}\n准备：{content.preparation}\n备选：{content.alternative}",
        ),
        section("下一课调整", f"保留：{content.keep_content}\n调整：{content.activity}\n检查：{content.check_method}"),
        section("采用与后续检查", "已采用" if plan.adopted else "尚未采用"),
    ]
    for observation in plan.observations:
        parts.append(section("教师后续记录", observation.text))
    if source.parent:
        parts.append(section("已发布家长反馈", source.parent.content.summary))
        parts.append(section("家庭活动", source.parent.content.home_activity))
    parts.append(
        section(
            "版本与依据",
            f"导出版本：{metadata.revision}\n生成时间：{metadata.created_at.isoformat()}\n"
            f"证据版本：{source.evidence.revision}\n教学安排版本：{plan.revision}",
        )
    )
    url = f"http://127.0.0.1:3000/api/exports/{metadata.id}/status"
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>教师教学支持报告</title>'
        "<style>body{font-family:system-ui,sans-serif;max-width:850px;margin:32px auto;padding:0 24px;line-height:1.7}"
        "p{white-space:pre-wrap}h1{font-size:26px}h2{font-size:19px}section{break-inside:avoid}"
        "@media print{body{margin:0;max-width:none}a{overflow-wrap:anywhere}}</style></head><body>"
        "<h1>教师教学支持报告</h1>"
        + "".join(parts)
        + "<footer><p>此文件是生成时的离线快照，已下载副本不能远程收回。使用前请查询当前状态；"
        "本机状态链接需要应用正在运行，其他设备需使用可达的部署地址。</p>"
        f'<a href="{escape(url, quote=True)}">{escape(url)}</a></footer></body></html>'
    )
