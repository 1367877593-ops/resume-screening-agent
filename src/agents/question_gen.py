"""试题生成。

题目要扎在简历的具体内容上，所以除了简历和 JD，还把匹配结论里的
「存疑项」喂进去 —— 面试真正的价值是验证简历里说不清楚的部分，
而不是再问一遍简历上已经写明白的事。
"""

from __future__ import annotations

import json
from typing import List, Optional

from pydantic import BaseModel, Field

from config.settings import get_settings, get_thresholds
from flywheel.retrieve import lessons_block
from harness.structured import call_structured
from schema.document import RawDoc
from schema.jd import JD
from schema.match import MatchResult
from schema.lesson import render_for_prompt
from schema.question import QuestionFull, QuestionSet


class _GeneratedQuestions(BaseModel):
    """LLM 输出边界：resume_id / jd_id 由代码补，不让模型转述。"""

    questions: List[QuestionFull] = Field(default_factory=list)


def _weak_points(jd: JD, match_result: MatchResult) -> str:
    """把 PARTIAL / NO 的判定整理成存疑清单，作为出题的重点方向。"""
    req_text = {r.requirement_id: r.text for r in jd.requirements}
    rows = [
        {
            "requirement": req_text.get(v.requirement_id, v.requirement_id),
            "satisfied": v.satisfied,
            "reason": v.reason,
        }
        for v in match_result.verdicts
        if v.satisfied in ("PARTIAL", "NO")
    ]
    if not rows:
        return "（本份简历各项要求均判定为满足，可围绕深度与真实性设计题目）"
    return json.dumps(rows, ensure_ascii=False, indent=2)


def generate_questions(
    jd: JD,
    match_result: MatchResult,
    resume_doc: RawDoc,
    model: Optional[str] = None,
) -> QuestionSet:
    min_count = get_thresholds()["question"]["min_count"]
    # 飞轮：把这个岗位以往被 Checker 打回的问题注入 prompt。
    # 关掉时注入固定的占位文本而不是省掉这一段 —— 让开关只影响内容、
    # 不改变 prompt 结构，缓存键的差异因此是可解释的。
    lessons = (
        lessons_block(jd.title, stage="question_set")
        if get_settings().flywheel_enabled
        else render_for_prompt([])
    )
    requirements = json.dumps(
        [{"requirement_id": r.requirement_id, "text": r.text} for r in jd.requirements],
        ensure_ascii=False,
        indent=2,
    )
    generated = call_structured(
        "question_gen",
        {
            "jd_title": jd.title,
            "requirements": requirements,
            "resume_text": resume_doc.full_text,
            "weak_points": _weak_points(jd, match_result),
            "min_count": min_count,
            "doc_id": resume_doc.doc_id,
            "lessons": lessons,
        },
        _GeneratedQuestions,
        model=model,
    )
    return QuestionSet(
        resume_id=match_result.resume_id,
        jd_id=jd.jd_id,
        questions=generated.questions,
    )
