"""面试题目。

QuestionFull / QuestionPublic 的切分是防泄题的核心机制：
三个作答人格的函数签名只接受 QuestionPublic，拿不到评分标准，
因此「不要把答案漏给模拟作答者」这件事由类型系统保证，
而不是写在 prompt 里请求模型自觉。
"""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field

from schema.document import SourceSpan

Difficulty = Literal["EASY", "MEDIUM", "HARD"]


class RubricLevel(BaseModel):
    """分档评分标准。绝不进入 persona 的 prompt。"""

    level: str = Field(description="如：优秀 / 合格 / 不合格")
    min_score: float = Field(ge=0, le=100)
    criteria: str


class QuestionPublic(BaseModel):
    """能给到模拟作答者的全部信息。字段增删需谨慎 —— 每加一个字段都是一次泄题风险。"""

    question_id: str
    text: str


class QuestionFull(BaseModel):
    question_id: str
    text: str
    skill_point: str = Field(description="考察点")
    difficulty: Difficulty
    rubric: List[RubricLevel] = Field(default_factory=list)
    source_requirement_ids: List[str] = Field(default_factory=list)
    evidence: List[SourceSpan] = Field(
        default_factory=list, description="题目所针对的简历原文依据"
    )

    def to_public(self) -> QuestionPublic:
        """唯一的转换入口。任何其它构造 QuestionPublic 的方式都是设计错误。"""
        return QuestionPublic(question_id=self.question_id, text=self.text)


class QuestionSet(BaseModel):
    resume_id: str
    jd_id: str
    questions: List[QuestionFull] = Field(default_factory=list)

    def to_public(self) -> List[QuestionPublic]:
        return [q.to_public() for q in self.questions]
