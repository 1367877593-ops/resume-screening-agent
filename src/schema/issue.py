"""Checker 的问题记录与放行判定。

Issue.detector 是这个项目的一个关键设计：它让「有多少问题是靠确定性规则抓到的、
多少是靠 LLM 抓到的」变成可统计的数字。如果绝大多数问题都靠 LLM 检出，
说明这套校验的可信度有限 —— 这个数字要公开，不藏。
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from schema.document import SourceSpan

Severity = Literal["blocker", "major", "minor"]
Detector = Literal["rule", "llm", "sim"]
GateStatus = Literal["PASS", "CONDITIONAL_PASS", "FAIL", "NEEDS_HUMAN_REVIEW"]


class Issue(BaseModel):
    issue_code: str = Field(description="如 EXT_SPAN_NOT_FOUND，稳定不变，供统计与检索")
    severity: Severity
    detector: Detector
    dimension: str = Field(description="校准维度：数据准确性 / 归因错误 / 格式与约束 / 题目质量 / 语义一致性")
    message: str
    target_path: Optional[str] = Field(
        default=None, description="问题所在位置，如 projects[2].evidence[0]"
    )
    suggestion: Optional[str] = None
    evidence: List[SourceSpan] = Field(default_factory=list)


class CheckReport(BaseModel):
    target_type: str = Field(description="resume / match / question_set / followup")
    target_id: str
    round_no: int = 0
    issues: List[Issue] = Field(default_factory=list)

    def count(self, severity: Severity) -> int:
        return sum(1 for i in self.issues if i.severity == severity)

    def by_detector(self) -> dict:
        """规则 vs LLM vs 模拟 的检出占比，直接进 README 的评测结果。"""
        out: dict = {}
        for i in self.issues:
            out[i.detector] = out.get(i.detector, 0) + 1
        return out


class GateResult(BaseModel):
    status: GateStatus
    reason: str
    blocker_count: int = 0
    major_count: int = 0
    minor_count: int = 0

    @property
    def passed(self) -> bool:
        return self.status in ("PASS", "CONDITIONAL_PASS")
