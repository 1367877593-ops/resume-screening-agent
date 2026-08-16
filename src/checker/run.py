"""四类校验目标的统一入口。每个都返回 (报告, 放行判定)。"""

from __future__ import annotations

from typing import Optional, Tuple

from config.settings import get_thresholds
from schema.document import RawDoc
from schema.followup import FollowUpSet
from schema.issue import CheckReport, GateResult
from schema.jd import JD
from schema.match import MatchResult
from schema.question import QuestionSet
from schema.resume import ExtractedResume
from schema.semantic import SemanticReport
from schema.simulation import SimulationReport

from checker import rules  # noqa: F401  导入即注册，不可删
from checker.base import RuleContext, run_rules
from checker.gate import evaluate_gate

Checked = Tuple[CheckReport, GateResult]


def _finish(target_type: str, target_id: str, ctx: RuleContext, round_no: int) -> Checked:
    report = run_rules(target_type, target_id, ctx, round_no=round_no)
    return report, evaluate_gate(report, round_no=round_no, thresholds=ctx.thresholds)


def check_resume(
    resume: ExtractedResume, resume_doc: RawDoc, round_no: int = 0, thresholds: Optional[dict] = None
) -> Checked:
    ctx = RuleContext(
        thresholds=thresholds or get_thresholds(), resume=resume, resume_doc=resume_doc
    )
    return _finish("resume", resume.resume_id, ctx, round_no)


def check_match(
    jd: JD,
    match_result: MatchResult,
    resume_doc: RawDoc,
    round_no: int = 0,
    thresholds: Optional[dict] = None,
    semantic: Optional[SemanticReport] = None,
) -> Checked:
    """`semantic` 为 None 时只跑确定性规则 —— 语义校验是可选增强，不是前置依赖。"""
    ctx = RuleContext(
        thresholds=thresholds or get_thresholds(),
        jd=jd,
        match_result=match_result,
        resume_doc=resume_doc,
        semantic=semantic,
    )
    return _finish("match", match_result.resume_id, ctx, round_no)


def check_question_set(
    question_set: QuestionSet,
    resume_doc: RawDoc,
    round_no: int = 0,
    thresholds: Optional[dict] = None,
    simulation: Optional[SimulationReport] = None,
) -> Checked:
    """`simulation` 为 None 时只跑确定性规则 —— 模拟是可选增强，不是前置依赖。"""
    ctx = RuleContext(
        thresholds=thresholds or get_thresholds(),
        question_set=question_set,
        resume_doc=resume_doc,
        simulation=simulation,
    )
    return _finish("question_set", question_set.resume_id, ctx, round_no)


def check_followups(
    followups: FollowUpSet,
    resume_doc: RawDoc,
    round_no: int = 0,
    thresholds: Optional[dict] = None,
) -> Checked:
    ctx = RuleContext(
        thresholds=thresholds or get_thresholds(), followups=followups, resume_doc=resume_doc
    )
    return _finish("followup", followups.resume_id, ctx, round_no)
