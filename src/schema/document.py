"""文档与出处。SourceSpan 是整个证据链的最小单元。"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SourceSpan(BaseModel):
    """一条结论的原文出处。

    为什么不要求模型给字符偏移：LLM 数不准偏移量，强行要求只会得到一个
    看起来精确、实际错位的数字。这里只要原文片段，由 checker/evidence.py
    在原文里做模糊匹配来验证它是否真实存在 —— 匹配不上即判定为归因错误。
    """

    doc_id: str
    text: str = Field(description="原文片段，必须能在 RawDoc.full_text 中找到")
    page: Optional[int] = None


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    order: int


class RawDoc(BaseModel):
    """归一化后的文档。JD 与简历共用这个结构。"""

    doc_id: str
    filename: str
    full_text: str
    chunks: List[Chunk] = Field(default_factory=list)
