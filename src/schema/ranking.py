"""多份简历的横向对比。这是 HR 场景真正要的东西：排序，不是单份报告。"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from schema.match import Recommendation


class RankedCandidate(BaseModel):
    rank: int
    resume_id: str
    candidate_name: Optional[str] = None
    total_score: float
    recommendation: Recommendation
    hard_requirement_failed: List[str] = Field(default_factory=list)


class CandidateRanking(BaseModel):
    jd_id: str
    items: List[RankedCandidate] = Field(default_factory=list)

    def advancing(self) -> List[RankedCandidate]:
        """只有这些候选人需要出题，被拒的不出。"""
        return [i for i in self.items if i.recommendation in ("ADVANCE", "HOLD")]
