"""唯一的状态机。

L1 主干：JD 拆解 -> 逐份提取 -> 逐份匹配 -> 排序与推进决策
-> 只对 ADVANCE/HOLD 的候选人出题与追问 -> 每步 check/revise 闭环。

修订循环写成一个通用函数而不是每处复制一遍：三处校验的退出条件必须一致，
复制粘贴迟早会长出三套不一样的熔断逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from agents.extractor import extract_resume
from agents.followup_gen import generate_followups
from agents.jd_parser import parse_jd
from agents.matcher import match
from agents.question_gen import generate_questions
from agents.reviser import revise
from agents.scorer import build_match_result, rank
from checker.run import check_followups, check_match, check_question_set, check_resume
from config.settings import get_thresholds
from schema.document import RawDoc
from schema.followup import FollowUpSet
from schema.issue import CheckReport, GateResult
from schema.jd import JD
from schema.match import MatchResult, MatchVerdicts
from schema.question import QuestionSet
from schema.ranking import CandidateRanking
from schema.resume import ExtractedResume
from schema.revision import RevisionNote


@dataclass
class StageOutcome:
    """一个校验目标经过 check/revise 后的最终状态，供 UI 展示 diff。"""

    stage: str
    report: CheckReport
    gate: GateResult
    rounds_used: int = 0
    notes: List[RevisionNote] = field(default_factory=list)


@dataclass
class CandidateOutcome:
    resume_id: str
    resume_doc: RawDoc
    resume: ExtractedResume
    match_result: MatchResult
    question_set: Optional[QuestionSet] = None
    followups: Optional[FollowUpSet] = None
    stages: List[StageOutcome] = field(default_factory=list)


@dataclass
class PipelineResult:
    jd: JD
    candidates: List[CandidateOutcome]
    ranking: CandidateRanking


def _revise_loop(
    obj,
    check_fn: Callable[[object, int], Tuple[CheckReport, GateResult]],
    stage: str,
    source_text: str,
    max_rounds: int,
    rebuild: Optional[Callable[[object], object]] = None,
):
    """校验 -> 不过则修订 -> 重新校验，直到通过或熔断。

    `rebuild` 用于匹配环节：模型修订的是 MatchVerdicts，
    修完必须重新过一遍 scorer 才能得到 MatchResult —— 分数永远由代码算。
    """
    notes: List[RevisionNote] = []
    rounds = 0
    checked = rebuild(obj) if rebuild else obj
    report, gate = check_fn(checked, rounds)

    while not gate.passed and gate.status != "NEEDS_HUMAN_REVIEW" and rounds < max_rounds:
        rounds += 1
        obj, round_notes = revise(obj, report.issues, source_text)
        notes.extend(round_notes)
        checked = rebuild(obj) if rebuild else obj
        report, gate = check_fn(checked, rounds)

    return checked, StageOutcome(stage=stage, report=report, gate=gate,
                                 rounds_used=rounds, notes=notes)


def run_pipeline(jd_doc: RawDoc, resume_docs: List[RawDoc]) -> PipelineResult:
    thresholds = get_thresholds()
    max_rounds = thresholds["gate"]["max_rounds"]

    jd = parse_jd(jd_doc)

    outcomes: List[CandidateOutcome] = []
    for doc in resume_docs:
        resume, resume_stage = _revise_loop(
            extract_resume(doc),
            lambda o, r, d=doc: check_resume(o, d, round_no=r),
            stage="extract",
            source_text=doc.full_text,
            max_rounds=max_rounds,
        )

        initial = match(jd, resume, doc)
        match_result, match_stage = _revise_loop(
            MatchVerdicts(verdicts=initial.verdicts),
            lambda o, r, d=doc: check_match(jd, o, d, round_no=r),
            stage="match",
            source_text=doc.full_text,
            max_rounds=max_rounds,
            # 修订的是判定，总分与推进决策每轮都由 scorer 重算
            rebuild=lambda mv, res=resume: build_match_result(
                jd, res.resume_id, mv.verdicts, candidate_name=res.candidate_name
            ),
        )

        outcomes.append(
            CandidateOutcome(
                resume_id=resume.resume_id, resume_doc=doc, resume=resume,
                match_result=match_result, stages=[resume_stage, match_stage],
            )
        )

    ranking = rank(jd.jd_id, [o.match_result for o in outcomes])
    advancing = {c.resume_id for c in ranking.advancing()}

    # 被淘汰的候选人不出题：既符合业务逻辑，也把调用量压下来一大截
    for outcome in outcomes:
        if outcome.resume_id not in advancing:
            continue
        doc = outcome.resume_doc

        qs, q_stage = _revise_loop(
            generate_questions(jd, outcome.match_result, doc),
            lambda o, r, d=doc: check_question_set(o, d, round_no=r),
            stage="question_set", source_text=doc.full_text, max_rounds=max_rounds,
        )
        fs, f_stage = _revise_loop(
            generate_followups(doc),
            lambda o, r, d=doc: check_followups(o, d, round_no=r),
            stage="followup", source_text=doc.full_text, max_rounds=max_rounds,
        )
        outcome.question_set = qs
        outcome.followups = fs
        outcome.stages.extend([q_stage, f_stage])

    return PipelineResult(jd=jd, candidates=outcomes, ranking=ranking)
