"""修订记录。

`DISPUTED` 是刻意留的口子：Checker 也会误判（尤其是归因规则遇到排版怪异的简历），
逼模型「必须改」会把正确内容改坏。允许它申辩，但必须说明理由，
申辩会原样呈现在 UI 上由人来裁决。
"""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field


class RevisionNote(BaseModel):
    issue_code: str
    action: Literal["FIXED", "DISPUTED"]
    detail: str = Field(description="改了什么，或为什么认为原判定成立")


class RevisionSummary(BaseModel):
    """一轮修订的结果摘要，供 UI 展示修订前后 diff。"""

    round_no: int
    notes: List[RevisionNote] = Field(default_factory=list)

    @property
    def fixed(self) -> List[RevisionNote]:
        return [n for n in self.notes if n.action == "FIXED"]

    @property
    def disputed(self) -> List[RevisionNote]:
        return [n for n in self.notes if n.action == "DISPUTED"]
