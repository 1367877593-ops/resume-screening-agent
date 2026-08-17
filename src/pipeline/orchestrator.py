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
from checker.semantic import check_match_semantics
from config.settings import get_settings, get_thresholds
from flywheel import record
from schema.document import RawDoc
from schema.lesson import normalize_job_kind
from schema.followup import FollowUpSet
from schema.issue import CheckReport, GateResult, Issue
from schema.jd import JD
from schema.match import MatchResult, MatchVerdicts
from schema.question import QuestionSet
from schema.ranking import CandidateRanking
from schema.resume import ExtractedResume
from schema.revision import RevisionNote
from schema.semantic import SemanticReport


@dataclass
class StageOutcome:
    """一个校验目标经过 check/revise 后的最终状态，供 UI 展示 diff。"""

    stage: str
    report: CheckReport
    gate: GateResult
    rounds_used: int = 0
    notes: List[RevisionNote] = field(default_factory=list)
    # 各轮累计检出的问题。`report` 只有最后一轮，被修好的问题不在里面 ——
    # 拿它统计「规则 vs LLM 检出占比」会把已修复的规则类检出全部漏掉，
    # 反而显得这套校验主要靠 LLM。这个字段是那个数字的正确来源。
    detected: List[Issue] = field(default_factory=list)


@dataclass
class CandidateOutcome:
    resume_id: str
    resume_doc: RawDoc
    resume: ExtractedResume
    match_result: MatchResult
    question_set: Optional[QuestionSet] = None
    followups: Optional[FollowUpSet] = None
    semantic: Optional[SemanticReport] = None
    stages: List[StageOutcome] = field(default_factory=list)


@dataclass
class PipelineResult:
    jd: JD
    candidates: List[CandidateOutcome]
    ranking: CandidateRanking
    # 由 pipeline.api.run() 填入，与 trace 的 run_id 是同一个，用于把
    # 「这次运行的结果」和「这次运行发出的调用」关联起来。
    run_id: Optional[str] = None


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
    detected: List[Issue] = []
    rounds = 0
    checked = rebuild(obj) if rebuild else obj
    report, gate = check_fn(checked, rounds)
    detected.extend(report.issues)

    while not gate.passed and gate.status != "NEEDS_HUMAN_REVIEW" and rounds < max_rounds:
        rounds += 1
        obj, round_notes = revise(
            obj, report.issues, source_text, model=revision_model
        )
        notes.extend(round_notes)
        checked = rebuild(obj) if rebuild else obj
        report, gate = check_fn(checked, rounds)
        detected.extend(report.issues)

    return checked, StageOutcome(stage=stage, report=report, gate=gate,
                                 rounds_used=rounds, notes=notes, detected=detected)


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
    semantic_holder: Dict[str, Optional[SemanticReport]] = {"report": None}
    match_result, match_stage = _revise_loop(
        MatchVerdicts(verdicts=initial.verdicts),
        _match_checker(jd, doc, semantic_holder, reasoning_model),
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
        semantic=semantic_holder["report"],
        stages=[resume_stage, match_stage],
    )


def _match_checker(
    jd: JD,
    doc: RawDoc,
    holder: Dict[str, Optional[SemanticReport]],
    model: Optional[str],
):
    """构造匹配阶段的校验函数：确定性规则 -> （通过后）语义校验。

    次序不能反。项目的核心主张之一是「能用规则判的绝不调 LLM」，而语义校验是
    唯一违反直觉的一层 —— 它必须排在最后，且只在前面全过时才跑，否则这条主张
    就只是口号。出现 blocker 时那批判定马上要被重写，对它做语义分析是纯浪费。
    """

    def check(match_result: MatchResult, round_no: int):
        report, gate = check_match(jd, match_result, doc, round_no=round_no)

        if not get_settings().semantic_check_enabled:
            return report, gate
        if report.count("blocker"):
            return report, gate

        holder["report"] = check_match_semantics(jd, match_result, model=model)
        return check_match(
            jd, match_result, doc, round_no=round_no, semantic=holder["report"]
        )

    return check


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
    if include_interview:
        generate_interviews(result)
    _write_lessons(result)
    return result


def _write_lessons(result: PipelineResult) -> None:
    """把本次 Checker 检出的问题沉淀进经验库。

    用 `detected`（各轮累计）而不是最后一轮的 report —— 被修好的问题恰恰是
    最该记住的：这次靠修订补救了，下次应该一开始就不犯。

    写入失败不应该让整条流水线失败：经验库是增强，不是主干。
    """
    if not get_settings().flywheel_enabled:
        return

    job_kind = normalize_job_kind(result.jd.title)
    issues: List[Issue] = []
    stage_of: Dict[str, str] = {}
    for outcome in result.candidates:
        for stage in outcome.stages:
            for issue in stage.detected:
                issues.append(issue)
                stage_of.setdefault(issue.issue_code, stage.stage)
    if not issues:
        return
    try:
        record(job_kind, issues, stage_of)
    except OSError:
        pass
