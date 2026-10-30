"""用一条虚构课堂回答验证真实模型，输出草稿，不自动确认或发布。"""

import sys

import httpx

from .deepseek import DeepSeek, GenerationError
from .models import VerifiedContext


def main() -> int:
    context = VerifiedContext(
        question_id="fraction-01",
        question_revision=1,
        objective="区分分成四份和平均分成四份",
        question="把一个长方形分成四块，任意一块都一定是原图形的四分之一吗？",
        reference_answer="不一定，必须把整体平均分成四份，每份才是整体的四分之一。",
        diagram_required=True,
        diagram_description="同一个长方形分成四块，面积分别占整体的二分之一、四分之一、八分之一、八分之一。",
        utterance_id="utterance-01",
        utterance_revision=1,
        student_alias="student-01",
        utterance="分成了四块，所以每一块都是四分之一。",
        text_confirmed=True,
        identity_confirmed=True,
        question_confirmed=True,
    )
    try:
        with httpx.Client(trust_env=False) as client:
            draft = DeepSeek.from_environment(client).analyze(context)
        print(draft.model_dump_json(indent=2))
        return 0
    except GenerationError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
