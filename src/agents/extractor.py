"""简历 -> 结构化信息。每个字段挂原文出处。"""

from __future__ import annotations

from harness.structured import call_structured
from schema.document import RawDoc
from schema.resume import ExtractedResume


def extract_resume(doc: RawDoc) -> ExtractedResume:
    resume = call_structured(
        "extract",
        {"resume_text": doc.full_text, "doc_id": doc.doc_id},
        ExtractedResume,
    )
    # resume_id 由代码指定：让模型自己编 id，多份简历之间可能撞号
    resume.resume_id = doc.doc_id
    return resume
