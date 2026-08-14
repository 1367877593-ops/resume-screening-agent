"""追问模拟。针对简历里说不清楚的地方，而不是泛泛地再问一遍。"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from schema.document import SourceSpan


class AmbiguityPoint(BaseModel):
    """简历中的模糊点。必须挂原文出处，否则无法验证这个「模糊」是不是模型编的。"""

    point_id: str
    description: str
    evidence: List[SourceSpan] = Field(default_factory=list)


class FollowUpQuestion(BaseModel):
    followup_id: str
    text: str
    ambiguity_point_id: str
    intent: str = Field(description="想通过这个追问确认什么")


class FollowUpSet(BaseModel):
    resume_id: str
    ambiguity_points: List[AmbiguityPoint] = Field(default_factory=list)
    questions: List[FollowUpQuestion] = Field(default_factory=list)
