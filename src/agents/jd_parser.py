"""JD -> 加权要求项。匹配打分的基准。"""

from __future__ import annotations

from typing import List

from harness.structured import call_structured
from pydantic import BaseModel, Field
from schema.document import RawDoc
from schema.jd import JD, Requirement


class _ParsedJD(BaseModel):
    """LLM 输出边界。jd_id / raw_text 由代码补，不劳烦模型转述原文。"""

    title: str
    requirements: List[Requirement] = Field(default_factory=list)


def parse_jd(doc: RawDoc) -> JD:
    parsed = call_structured("jd_parse", {"jd_text": doc.full_text}, _ParsedJD)
    return JD(
        jd_id=doc.doc_id,
        title=parsed.title,
        raw_text=doc.full_text,
        requirements=parsed.requirements,
    )
