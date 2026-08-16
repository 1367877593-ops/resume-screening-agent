"""规则注册表与调度。

设计目标只有一个：**新增一条校验规则时不需要碰调度代码**。
写一个函数、挂上 @register("match")，它就会被跑到。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from schema.document import RawDoc
from schema.followup import FollowUpSet
from schema.issue import CheckReport, Issue
from schema.jd import JD
from schema.match import MatchResult
from schema.question import QuestionSet
from schema.resume import ExtractedResume
from schema.semantic import SemanticReport
from schema.simulation import SimulationReport


@dataclass
class RuleContext:
    """规则能看到的全部东西。

    新增规则若需要新的输入，在这里加字段即可，不影响已有规则的签名。
    """

    thresholds: Dict
    jd: Optional[JD] = None
    resume: Optional[ExtractedResume] = None
    resume_doc: Optional[RawDoc] = None
    match_result: Optional[MatchResult] = None
    question_set: Optional[QuestionSet] = None
    followups: Optional[FollowUpSet] = None
    # 三人格盲评的诊断结论（L2）。模拟本身在 checker/simulation/ 里完成，
    # 规则只负责把结论翻译成 Issue —— 规则函数不发起 LLM 调用。
    simulation: Optional[SimulationReport] = None
    # 语义一致性校验结论。同上：调用在 checker/semantic.py，规则只做翻译。
    semantic: Optional[SemanticReport] = None
    extra: Dict = field(default_factory=dict)


Rule = Callable[[RuleContext], List[Issue]]

_REGISTRY: Dict[str, List[Rule]] = defaultdict(list)


def register(target_type: str) -> Callable[[Rule], Rule]:
    """把规则挂到某个校验目标上。target_type: resume / match / question_set / followup"""

    def deco(fn: Rule) -> Rule:
        _REGISTRY[target_type].append(fn)
        return fn

    return deco


def registered_rules(target_type: str) -> List[Rule]:
    return list(_REGISTRY[target_type])


def run_rules(target_type: str, target_id: str, ctx: RuleContext, round_no: int = 0) -> CheckReport:
    """跑完某个目标下注册的所有规则。

    单条规则抛异常不应该让整轮校验崩掉 —— 那会让一个边角 bug 拖垮
    整条流水线。捕获后记成 minor，让问题可见但不阻断。
    """
    issues: List[Issue] = []
    for rule in _REGISTRY[target_type]:
        try:
            issues.extend(rule(ctx) or [])
        except Exception as e:  # noqa: BLE001
            issues.append(
                Issue(
                    issue_code="RULE_CRASHED",
                    severity="minor",
                    detector="rule",
                    dimension="格式与约束",
                    message=f"规则 {getattr(rule, '__name__', rule)} 执行失败：{type(e).__name__}: {e}",
                )
            )
    return CheckReport(
        target_type=target_type, target_id=target_id, round_no=round_no, issues=issues
    )
