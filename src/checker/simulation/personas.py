"""三个作答人格。

**信息隔离由函数签名保证。** 三个函数的题目参数类型都是 `QuestionPublic`，
它只有 `question_id` 和 `text` 两个字段 —— 评分标准、考察点、难度、简历出处
根本不在这个类型里，所以「不要把答案漏给作答者」不是 prompt 里的一句请求，
而是类型系统的结论。

想给人格多喂一点信息，得先去 `schema/question.py` 里给 `QuestionPublic`
加字段，那是一次显式的、会被 review 看到的改动。
"""

from __future__ import annotations

import json
from typing import List, Optional

from pydantic import BaseModel, Field

from harness.structured import call_structured
from schema.jd import JD
from schema.question import QuestionPublic
from schema.simulation import SimAnswer


class _Answer(BaseModel):
    question_id: str
    answer: str


class _AnswerSheet(BaseModel):
    """LLM 输出边界：人格由调用方标注，不让模型自报身份。"""

    answers: List[_Answer] = Field(default_factory=list)


def _render(questions: List[QuestionPublic]) -> str:
    """题目序列化。

    这里直接 dump `QuestionPublic`，而不是从 `QuestionFull` 里挑字段 ——
    挑字段的写法总有一天会手滑多带一个出来。
    """
    return json.dumps([q.model_dump() for q in questions], ensure_ascii=False, indent=2)


def _jd_context(jd: JD) -> str:
    return json.dumps(
        [{"text": r.text, "category": r.category} for r in jd.requirements],
        ensure_ascii=False,
        indent=2,
    )


def _to_answers(sheet: _AnswerSheet, persona: str) -> List[SimAnswer]:
    return [
        SimAnswer(question_id=a.question_id, persona=persona, answer=a.answer)
        for a in sheet.answers
    ]


def answer_as_expert(
    questions: List[QuestionPublic], jd: JD, model: Optional[str] = None
) -> List[SimAnswer]:
    """理想专家：信息最全。他答不出的题，就是题目本身有问题。"""
    sheet = call_structured(
        "persona_expert",
        {"jd_title": jd.title, "jd_context": _jd_context(jd), "questions": _render(questions)},
        _AnswerSheet,
        model=model,
    )
    return _to_answers(sheet, "expert")


def answer_as_bluffer(
    questions: List[QuestionPublic], model: Optional[str] = None
) -> List[SimAnswer]:
    """背题党：只有通用面经。他答得漂亮的题，说明这题在考背诵。

    注意这里连 JD 都不给 —— 背题党对目标岗位一无所知，这正是他和专家的差别。
    """
    sheet = call_structured(
        "persona_bluffer",
        {"questions": _render(questions)},
        _AnswerSheet,
        model=model,
    )
    return _to_answers(sheet, "bluffer")


def answer_as_resume(
    questions: List[QuestionPublic], resume_text: str, model: Optional[str] = None
) -> List[SimAnswer]:
    """简历人格：只能用简历里写过的东西作答。他答不出，说明题超出了候选人射程。"""
    sheet = call_structured(
        "persona_resume",
        {"resume_text": resume_text, "questions": _render(questions)},
        _AnswerSheet,
        model=model,
    )
    return _to_answers(sheet, "resume")
