"""总分与推进决策。**本模块不得调用 LLM。**

为什么把这段逻辑从模型手里拿走：
- 让模型直接给「85 分」，同一份简历跑两次可能给出 82 和 88，分数不可复现；
- 模型也算不准加权平均，要求它做算术只是徒增一个失败点；
- 「是否推进面试」是会影响到真人的决定，它的依据必须能被逐条复核。

所以模型只回答「这一条要求满足吗、依据是哪句原文」，
剩下的加权、排序、卡阈值全部是确定性代码，可单测、可复现、可解释。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from config.settings import get_thresholds
from schema.jd import JD
from schema.match import MatchResult, Recommendation, RequirementVerdict
from schema.ranking import CandidateRanking, RankedCandidate


def normalized_weights(jd: JD) -> Dict[str, float]:
    """把 JD 的相对权重归一化到和为 1。

    模型给的权重不要求和为 100，这里统一归一化。全为 0 时退化成等权，
    而不是除零崩溃 —— 一份权重全 0 的 JD 是模型输出异常，
    但它不该让整个流程挂掉，该由 Checker 去报告。
    """
    total = sum(max(r.weight, 0.0) for r in jd.requirements)
    if total <= 0:
        n = len(jd.requirements)
        return {r.requirement_id: 1.0 / n for r in jd.requirements} if n else {}
    return {r.requirement_id: max(r.weight, 0.0) / total for r in jd.requirements}


def aggregate_score(jd: JD, verdicts: List[RequirementVerdict]) -> float:
    """加权求和。

    JD 里有、但模型没给判定的要求项按 0 分计入。
    不能跳过它们 —— 跳过等于把「漏答」变成「不影响总分」，
    模型少答几条反而分数更高。漏判本身由 Checker 报 MATCH_VERDICT_MISSING。
    """
    weights = normalized_weights(jd)
    by_id = {v.requirement_id: v for v in verdicts}
    total = 0.0
    for req in jd.requirements:
        v = by_id.get(req.requirement_id)
        total += weights.get(req.requirement_id, 0.0) * (v.score if v else 0.0)
    return round(total, 2)


def find_hard_failures(jd: JD, verdicts: List[RequirementVerdict]) -> List[str]:
    """硬性要求未满足项。缺判定按未满足处理 —— 存疑时不放行。"""
    by_id = {v.requirement_id: v for v in verdicts}
    failed: List[str] = []
    for req in jd.requirements:
        if not req.is_hard:
            continue
        v = by_id.get(req.requirement_id)
        if v is None or v.satisfied == "NO":
            failed.append(req.text)
    return failed


def decide(
    score: float, hard_failed: List[str], thresholds: Optional[Dict] = None
) -> Recommendation:
    """判定顺序固定：硬性项一票否决 -> 推进线 -> 待定线。"""
    t = (thresholds or get_thresholds())["match"]
    if hard_failed:
        return "REJECT"
    if score >= t["advance"]:
        return "ADVANCE"
    if score >= t["hold"]:
        return "HOLD"
    return "REJECT"


def build_reason(
    jd: JD,
    verdicts: List[RequirementVerdict],
    recommendation: Recommendation,
    hard_failed: List[str],
    score: float,
) -> str:
    """拼装决策理由。

    刻意用代码拼而不是让模型写：理由必须和实际判定严格一致。
    模型写的理由读起来更顺，但可能和它自己给的 verdict 打架 ——
    那是最难被发现、也最不该出现的一类错误。
    """
    if hard_failed:
        return "硬性要求未满足：" + "；".join(hard_failed[:3])

    req_text = {r.requirement_id: r.text for r in jd.requirements}
    weights = normalized_weights(jd)
    ranked = sorted(
        verdicts, key=lambda v: weights.get(v.requirement_id, 0.0) * v.score, reverse=True
    )
    strong = [v for v in ranked if v.satisfied == "YES"][:2]
    weak = [v for v in reversed(ranked) if v.satisfied in ("NO", "PARTIAL")][:2]

    parts = [f"综合得分 {score:.1f}"]
    if strong:
        parts.append("优势：" + "；".join(req_text.get(v.requirement_id, v.requirement_id) for v in strong))
    if weak:
        parts.append("短板：" + "；".join(req_text.get(v.requirement_id, v.requirement_id) for v in weak))
    verb = {"ADVANCE": "建议推进面试", "HOLD": "建议待定", "REJECT": "建议淘汰"}[recommendation]
    return f"{verb}（" + "，".join(parts) + "）"


def build_match_result(
    jd: JD,
    resume_id: str,
    verdicts: List[RequirementVerdict],
    candidate_name: Optional[str] = None,
    thresholds: Optional[Dict] = None,
) -> MatchResult:
    """把模型的逐项判定组装成完整结果。这是 MatchResult 唯一的构造入口。"""
    score = aggregate_score(jd, verdicts)
    hard_failed = find_hard_failures(jd, verdicts)
    rec = decide(score, hard_failed, thresholds)
    return MatchResult(
        resume_id=resume_id,
        jd_id=jd.jd_id,
        total_score=score,
        verdicts=verdicts,
        recommendation=rec,
        recommendation_reason=build_reason(jd, verdicts, rec, hard_failed, score),
        hard_requirement_failed=hard_failed,
        candidate_name=candidate_name,
    )


def rank(jd_id: str, results: List[MatchResult]) -> CandidateRanking:
    """排序：硬性项未过的永远沉底，其余按总分降序。

    并列时用 resume_id 兜底排序，保证同样输入下顺序稳定 ——
    否则演示两次看到的排名不一样，很难解释。
    """
    ordered = sorted(
        results,
        key=lambda r: (bool(r.hard_requirement_failed), -r.total_score, r.resume_id),
    )
    return CandidateRanking(
        jd_id=jd_id,
        items=[
            RankedCandidate(
                rank=i,
                resume_id=r.resume_id,
                candidate_name=r.candidate_name,
                total_score=r.total_score,
                recommendation=r.recommendation,
                hard_requirement_failed=r.hard_requirement_failed,
            )
            for i, r in enumerate(ordered, start=1)
        ],
    )
