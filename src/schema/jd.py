"""JD 拆解结果。加权要求项是匹配打分的基准。"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class Requirement(BaseModel):
    """JD 中的一条要求。

    weight 是相对权重，代码侧归一化后使用，因此不要求模型给出的权重和为 100 ——
    要求模型做算术只会引入不必要的失败点。
    """

    requirement_id: str
    text: str
    weight: float = Field(ge=0, description="相对权重，代码侧归一化")
    is_hard: bool = Field(default=False, description="硬性要求：不满足则一票否决")
    category: str = "其他"


class JD(BaseModel):
    jd_id: str
    title: str
    raw_text: str
    requirements: List[Requirement] = Field(default_factory=list)
