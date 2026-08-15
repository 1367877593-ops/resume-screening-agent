"""逐项匹配判定。

注意返回类型是 `MatchVerdicts` 而不是 `MatchResult` —— 模型给不出总分和
推进决策，那是 `scorer.py` 的事。这个边界由类型保证，不是靠 prompt 里叮嘱。
"""

from __future__ import annotations

import json
from typing import Optional

from harness.structured import call_structured
from schema.document import RawDoc
from schema.jd import JD
from schema.match import MatchResult, MatchVerdicts
from schema.resume import ExtractedResume

from agents.scorer import build_match_result


def match(
    jd: JD,
    resume: ExtractedResume,
    resume_doc: RawDoc,
    model: Optional[str] = None,
) -> MatchResult:
    requirements = json.dumps(
        [
            {"requirement_id": r.requirement_id, "text": r.text, "is_hard": r.is_hard}
            for r in jd.requirements
        ],
        ensure_ascii=False,
        indent=2,
    )
    verdicts: MatchVerdicts = call_structured(
        "match",
        {
            "jd_title": jd.title,
            "requirements": requirements,
            "resume_text": resume_doc.full_text,
            "doc_id": resume_doc.doc_id,
        },
        MatchVerdicts,
        model=model,
    )
    # 组装（加权、卡阈值、拼理由）全部在 scorer 里，此处不做任何判定
    return build_match_result(
        jd=jd,
        resume_id=resume.resume_id,
        verdicts=verdicts.verdicts,
        candidate_name=resume.candidate_name,
    )
