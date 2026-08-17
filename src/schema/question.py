"""面试题目。

每道题都必须说清楚「考察什么」与「为什么问这位候选人」：
前者是 `skill_point`，后者是 `rationale`。没有这两项的题目，
面试官无从判断该不该问，也无从判断答成什么样算过关。
"""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field

from schema.document import SourceSpan

Difficulty = Literal["EASY", "MEDIUM", "HARD"]


class RubricLevel(BaseModel):
    """分档评分标准：什么样的回答算优秀 / 合格 / 不合格。"""

    level: str = Field(description="如：优秀 / 合格 / 不合格")
    min_score: float = Field(ge=0, le=100)
    criteria: str


class QuestionFull(BaseModel):
    question_id: str
    text: str
    skill_point: str = Field(description="考察点：这道题想验证候选人的哪项能力")
    rationale: str = Field(
        default="",
        description="出题原因：为什么要对这位候选人问这道题，"
        "指向简历里的哪个存疑点或岗位的哪条要求",
    )
    difficulty: Difficulty
    rubric: List[RubricLevel] = Field(default_factory=list)
    source_requirement_ids: List[str] = Field(default_factory=list)
    evidence: List[SourceSpan] = Field(
        default_factory=list, description="题目所针对的简历原文依据"
    )


class QuestionSet(BaseModel):
    resume_id: str
    jd_id: str
    questions: List[QuestionFull] = Field(default_factory=list)
