"""唯一的状态机。

L1 主干：JD 拆解 -> 逐份提取 -> 逐份匹配 -> 排序与推进决策
-> 只对 ADVANCE/HOLD 的候选人出题与追问 -> 每步 check/revise 闭环。

修订循环写成一个通用函数而不是每处复制一遍：三处校验的退出条件必须一致，
复制粘贴迟早会长出三套不一样的熔断逻辑。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
from config.settings import get_settings, get_thresholds
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
    revision_model: Optional[str] = None,
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
        obj, round_notes = revise(
            obj, report.issues, source_text, model=revision_model
        )
        notes.extend(round_notes)
        checked = rebuild(obj) if rebuild else obj
        report, gate = check_fn(checked, rounds)

    return checked, StageOutcome(stage=stage, report=report, gate=gate,
                                 rounds_used=rounds, notes=notes)


def _stage_models() -> Tuple[Optional[str], Optional[str]]:
    """返回（快速模型，关键判断模型）。Demo 必须继续使用稳定缓存命名空间。"""
    settings = get_settings()
    if settings.demo_mode:
        return None, None
    return settings.llm_model_cheap, settings.llm_model


def _screen_candidate(
    jd: JD,
    doc: RawDoc,
    max_rounds: int,
    fast_model: Optional[str],
    reasoning_model: Optional[str],
) -> CandidateOutcome:
    """完成单个候选人的提取与匹配；候选人之间可安全并行。"""
    resume, resume_stage = _revise_loop(
        extract_resume(doc, model=fast_model),
        lambda o, r, d=doc: check_resume(o, d, round_no=r),
        stage="extract",
        source_text=doc.full_text,
        max_rounds=max_rounds,
        revision_model=reasoning_model,
    )

    initial = match(jd, resume, doc, model=reasoning_model)
    match_result, match_stage = _revise_loop(
        MatchVerdicts(verdicts=initial.verdicts),
        lambda o, r, d=doc: check_match(jd, o, d, round_no=r),
        stage="match",
        source_text=doc.full_text,
        max_rounds=max_rounds,
        rebuild=lambda mv, res=resume: build_match_result(
            jd, res.resume_id, mv.verdicts, candidate_name=res.candidate_name
        ),
        revision_model=reasoning_model,
    )
    return CandidateOutcome(
        resume_id=resume.resume_id,
        resume_doc=doc,
        resume=resume,
        match_result=match_result,
        stages=[resume_stage, match_stage],
    )


def _generate_interview(
    jd: JD,
    outcome: CandidateOutcome,
    max_rounds: int,
    fast_model: Optional[str],
    reasoning_model: Optional[str],
) -> None:
    """按需补充一名候选人的题目与追问，重复调用时保持幂等。"""
    doc = outcome.resume_doc
    if outcome.question_set is None:
        qs, q_stage = _revise_loop(
            generate_questions(
                jd, outcome.match_result, doc, model=fast_model
            ),
            lambda o, r, d=doc: check_question_set(o, d, round_no=r),
            stage="question_set",
            source_text=doc.full_text,
            max_rounds=max_rounds,
            revision_model=reasoning_model,
        )
        outcome.question_set = qs
        outcome.stages.append(q_stage)

    if outcome.followups is None:
        fs, f_stage = _revise_loop(
            generate_followups(doc, model=fast_model),
            lambda o, r, d=doc: check_followups(o, d, round_no=r),
            stage="followup",
            source_text=doc.full_text,
            max_rounds=max_rounds,
            revision_model=reasoning_model,
        )
        outcome.followups = fs
        outcome.stages.append(f_stage)


def generate_interviews(
    result: PipelineResult,
    resume_ids: Optional[List[str]] = None,
) -> PipelineResult:
    """为已完成排名的候选人按需生成面试材料。

    只允许 ADVANCE/HOLD，既节省模型调用，也避免 UI 绕过业务规则。
    """
    settings = get_settings()
    max_rounds = get_thresholds()["gate"]["max_rounds"]
    fast_model, reasoning_model = _stage_models()
    advancing = {c.resume_id for c in result.ranking.advancing()}
    selected = set(resume_ids) if resume_ids is not None else advancing
    targets = [
        o for o in result.candidates
        if o.resume_id in advancing and o.resume_id in selected
    ]

    def enrich(outcome: CandidateOutcome) -> None:
        _generate_interview(
            result.jd, outcome, max_rounds, fast_model, reasoning_model
        )

    workers = min(settings.max_parallel_candidates, len(targets))
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(enrich, targets))
    else:
        for target in targets:
            enrich(target)
    return result


def run_pipeline(
    jd_doc: RawDoc,
    resume_docs: List[RawDoc],
    include_interview: bool = True,
) -> PipelineResult:
    thresholds = get_thresholds()
    max_rounds = thresholds["gate"]["max_rounds"]
    settings = get_settings()
    fast_model, reasoning_model = _stage_models()

    jd = parse_jd(jd_doc, model=fast_model)

    def screen(doc: RawDoc) -> CandidateOutcome:
        return _screen_candidate(
            jd, doc, max_rounds, fast_model, reasoning_model
        )

    # executor.map 保持输入顺序，排名之前的数据结构仍然是确定性的。
    workers = min(settings.max_parallel_candidates, len(resume_docs))
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            outcomes = list(executor.map(screen, resume_docs))
    else:
        outcomes = [screen(doc) for doc in resume_docs]

    ranking = rank(jd.jd_id, [o.match_result for o in outcomes])
    result = PipelineResult(jd=jd, candidates=outcomes, ranking=ranking)
    return generate_interviews(result) if include_interview else result
