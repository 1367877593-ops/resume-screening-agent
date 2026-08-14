"""追问生成。针对简历里说不清楚的地方，不是针对简历没写的东西。"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from config.settings import get_thresholds
from harness.structured import call_structured
from schema.document import RawDoc
from schema.followup import AmbiguityPoint, FollowUpQuestion, FollowUpSet


class _GeneratedFollowUps(BaseModel):
    ambiguity_points: List[AmbiguityPoint] = Field(default_factory=list)
    questions: List[FollowUpQuestion] = Field(default_factory=list)


def generate_followups(resume_doc: RawDoc) -> FollowUpSet:
    t = get_thresholds()["followup"]
    generated = call_structured(
        "followup",
        {
            "resume_text": resume_doc.full_text,
            "doc_id": resume_doc.doc_id,
            "min_count": t["min_count"],
            "max_count": t["max_count"],
        },
        _GeneratedFollowUps,
    )
    return FollowUpSet(
        resume_id=resume_doc.doc_id,
        ambiguity_points=generated.ambiguity_points,
        questions=generated.questions,
    )
