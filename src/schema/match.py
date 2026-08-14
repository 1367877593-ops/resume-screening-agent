"""匹配打分与推进决策。

这里有一个刻意的类型切分：LLM 只能产出 `MatchVerdicts`（逐项判定），
`MatchResult`（含总分与推进决策）只能由 `agents/scorer.py` 组装。
「分数由代码算」这条约束因此由类型保证，而不是靠 prompt 里嘱咐模型别算总分。
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from schema.document import SourceSpan

Satisfied = Literal["YES", "PARTIAL", "NO"]
Recommendation = Literal["ADVANCE", "HOLD", "REJECT"]


class RequirementVerdict(BaseModel):
    """对 JD 中单条要求的判定。reason 必须能被 evidence 支撑。"""

    requirement_id: str
    satisfied: Satisfied
    score: float = Field(ge=0, le=100, description="本项得分，0-100")
    reason: str
    evidence: List[SourceSpan] = Field(
        default_factory=list,
        description="支撑该判定的简历原文；空 evidence 会被 Checker 判为归因错误",
    )


class MatchVerdicts(BaseModel):
    """matcher 的 LLM 输出边界 —— 没有总分，没有推进决策。"""

    verdicts: List[RequirementVerdict] = Field(default_factory=list)


class MatchResult(BaseModel):
    """完整匹配结果。由 scorer.py 组装，LLM 无法直接产出。"""

    resume_id: str
    jd_id: str
    total_score: float = Field(ge=0, le=100, description="代码加权得出")
    verdicts: List[RequirementVerdict] = Field(default_factory=list)
    recommendation: Recommendation
    recommendation_reason: str = Field(description="必须引用具体 verdict，不得空泛")
    hard_requirement_failed: List[str] = Field(default_factory=list)
    candidate_name: Optional[str] = None
